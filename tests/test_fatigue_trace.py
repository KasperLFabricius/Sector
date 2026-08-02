"""CT-010 reinforcement fatigue trace: oracles, inventory, identity, graph.

The oracle tests are independent of the traced kernels: cracked-rectangle
steel stresses, the two-slope S-N life at both exponent branches, the
Palmgren-Miner sum, the 2005 mixed-bond eta and the yield screen are
recomputed with plain closed forms and compared against the sealed steps and
the published fatigue payload. Concrete fatigue members are the named
PR-08D.3b exclusions throughout.
"""

from __future__ import annotations

import copy
import dataclasses
import math
import pathlib
import sys
from collections.abc import Mapping

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import fatigue_analysis  # noqa: E402
import fatigue_inputs  # noqa: E402
import material_catalog as mat_catalog  # noqa: E402
import sector.fatigue as fatigue_mod  # noqa: E402
from sector import codes  # noqa: E402
from sector.calculation_trace import (  # noqa: E402
    RESULT_FAILED, RESULT_FINITE, RESULT_NEGATIVE_INFINITY,
    RESULT_POSITIVE_INFINITY, RESULT_UNDEFINED, ROLE_COMPUTED, ROLE_FINAL,
    ROLE_USER_INPUT, TraceDependency, TraceUnit,
    TraceValidationError, bundle_to_json, seal_bundle, trace_identity_token,
)
from sector.fatigue_trace import (  # noqa: E402
    _calculation, build_fatigue_trace_family, validate_fatigue_trace_family,
)
from sector.fatigue_trace_contract import (  # noqa: E402
    ADAPTER_SOURCE, BIN_RESULT_FIELDS, BOND_SOURCES, COVERAGE_ID, EDITIONS,
    FAMILY_ID, INPUT_SOURCE, INVALID_KEYS, METHOD_ID, MM, ONE, REGISTRY_ID,
    RESULT_FIELDS, SN_SOURCES, STATUS_CODES, VALID_KEYS, _Rows, bin_prefix,
)
from sector.section import Section  # noqa: E402


INPUT_SHA, RESULT_SHA = "a" * 64, "b" * 64
CONTEXT = {"case": "CT-010 fatigue"}

# Rectangular anchor beam 0.3 x 0.6 m, one 982 mm2 bar at y = 0.05 (d = 0.55),
# modular ratio 6: the cracked lever arm and steel stress are closed forms.
B, H, D_EFF = 0.3, 0.6, 0.55
AS = 982.0e-6
N_RATIO = 6.0
# 2005 straight-bar detail F1: N* = 1e6, k1 = 5, k2 = 9, Rsk = 162.5 MPa.
N_STAR, K1, K2, RSK = 1.0e6, 5.0, 9.0, 162.5
GAMMA_S = 1.15


@pytest.fixture(autouse=True)
def _isolate_autosave(monkeypatch):
    monkeypatch.setenv("SECTOR_AUTOSAVE_DIR", "ct010-fatigue-no-autosave")


def _sigma_mpa(moment_knm: float, b=B, d=D_EFF, area=AS) -> float:
    """Closed-form cracked-rectangle steel stress in pure sagging."""

    na = N_RATIO * area
    x = (-na + math.sqrt(na * na + 2.0 * b * na * d)) / b
    return moment_knm / (area * (d - x / 3.0)) / 1000.0


def _life_log10(design_range: float) -> tuple[float, float]:
    """Closed-form retained two-slope life: (exponent, log10 N)."""

    knee = RSK / GAMMA_S
    exponent = K1 if design_range >= knee else K2
    return exponent, math.log10(N_STAR) + exponent * math.log10(
        RSK / (GAMMA_S * design_range))


def _steel_only_input(**over):
    entry = mat_catalog.default_entry(
        "mild", material_id="B500", preset=codes.EC2_2005.label)
    steel = mat_catalog.build_material(entry, "mild")
    section = Section.from_polygon(
        corners=[(0.0, 0.0), (B, 0.0), (B, H), (0.0, H)],
        bars_xy_area_mm2=[(0.15, 0.05, 982.0)],
    )
    table = fatigue_inputs.normalise_spectrum_table([
        {"spectrum": "S1", "name": "FAT-1", "cycles": 1.0e5,
         "mx_long_ed_knm": 100.0, "mx_short_ed_knm": 80.0},
        {"spectrum": "S1", "name": "FAT-2", "cycles": 1.0e7,
         "mx_long_ed_knm": 100.0, "mx_short_ed_knm": 20.0},
    ])
    inp = {
        "fatigue_on": True,
        "fatigue_edition": fatigue_inputs.EC2_2005,
        "fatigue_check_steel": True,
        "fatigue_check_concrete": False,
        "fatigue_gamma_s": GAMMA_S,
        "fatigue_gamma_ff": 1.0,
        fatigue_inputs.DETAIL_CATALOG_KEY: fatigue_inputs.default_catalog(),
        fatigue_inputs.SPECTRUM_TABLE_KEY: table,
        "section": section,
        "concrete": codes.EC2_2005.concrete(30.0),
        "concrete_preset": codes.EC2_2005.label,
        "bar_elements": [{
            "id": "B-1", "x_mm": 150.0, "y_mm": 50.0, "area_mm2": 982.0,
            "diameter_mm": 25.0, "material_id": "B500",
            "fatigue_detail_id": "F1",
        }],
        "bar_materials": [steel],
        mat_catalog.MILD_CATALOG_KEY:
            {"version": 1, "next_id": 2, "items": [entry]},
        "nl": 6.0, "ns": 6.0,
    }
    inp.update(over)
    return inp


def _mixed_input(edition=fatigue_inputs.EC2_2005, **over):
    mild_entry = mat_catalog.default_entry(
        "mild", material_id="B500", preset=codes.EC2_2005.label)
    steel = mat_catalog.build_material(mild_entry, "mild")
    tendon_entry = mat_catalog.default_entry("prestress", material_id="P-1")
    tendon_entry["IS"] = 0.002
    prestress = mat_catalog.build_material(tendon_entry, "prestress")
    section = Section.from_polygon(
        corners=[(0.0, 0.0), (B, 0.0), (B, H), (0.0, H)],
        bars_xy_area_mm2=[(0.075, 0.05, 491.0), (0.225, 0.05, 491.0)],
        tendons_xy_area_mm2=[(0.15, 0.10, 1000.0)],
    )
    catalogue = fatigue_inputs.default_catalog()
    if "2023" in edition:
        catalogue["items"][0] = fatigue_inputs.apply_preset(
            catalogue["items"][0], fatigue_inputs.PRESET_2023_BARS)
    catalogue, tendon_detail = fatigue_inputs.add_entry(
        catalogue,
        preset=(fatigue_inputs.PRESET_2023_PRETENSION if "2023" in edition
                else fatigue_inputs.PRESET_2005_PRETENSION))
    detail = next(item for item in catalogue["items"]
                  if item["id"] == tendon_detail)
    detail["bond_ratio_xi"] = 0.5
    detail["bond_equivalent_diameter_mm"] = 40.0
    catalogue = fatigue_inputs.replace_entry(catalogue, detail)
    table = fatigue_inputs.normalise_spectrum_table([
        {"spectrum": "S1", "name": "FAT-1", "cycles": 1.0e6,
         "mx_long_ed_knm": 120.0, "mx_short_ed_knm": 60.0},
        {"spectrum": "S2", "name": "FAT-2", "cycles": 2.0e6,
         "mx_long_ed_knm": 120.0, "mx_short_ed_knm": 90.0},
    ])
    inp = {
        "fatigue_on": True,
        "fatigue_edition": edition,
        "fatigue_check_steel": True,
        "fatigue_check_concrete": False,
        "fatigue_gamma_s": GAMMA_S,
        "fatigue_gamma_ff": 1.0,
        fatigue_inputs.DETAIL_CATALOG_KEY: catalogue,
        fatigue_inputs.SPECTRUM_TABLE_KEY: table,
        "section": section,
        "concrete": codes.EC2_2005.concrete(30.0),
        "concrete_preset": codes.EC2_2005.label,
        "bar_elements": [
            {"id": "B-1", "x_mm": 75.0, "y_mm": 50.0, "area_mm2": 491.0,
             "diameter_mm": 25.0, "material_id": "B500",
             "fatigue_detail_id": "F1"},
            {"id": "B-2", "x_mm": 225.0, "y_mm": 50.0, "area_mm2": 491.0,
             "diameter_mm": 25.0, "material_id": "B500",
             "fatigue_detail_id": "F1"},
        ],
        "tendon_elements": [
            {"id": "T-1", "x_mm": 150.0, "y_mm": 100.0, "area_mm2": 1000.0,
             "diameter_mm": 15.2, "material_id": "P-1",
             "fatigue_detail_id": tendon_detail},
        ],
        "bar_materials": [steel, steel],
        "tendon_materials": [prestress],
        mat_catalog.MILD_CATALOG_KEY:
            {"version": 1, "next_id": 2, "items": [mild_entry]},
        mat_catalog.PRESTRESS_CATALOG_KEY:
            {"version": 1, "next_id": 2, "items": [tendon_entry]},
        "nl": 6.0, "ns": 6.0,
    }
    inp.update(over)
    return inp


def _two_element_input(**over):
    """Steel-only 2-spectrum, 2-element graph-battery fixture (1 bin each)."""

    entry = mat_catalog.default_entry(
        "mild", material_id="B500", preset=codes.EC2_2005.label)
    steel = mat_catalog.build_material(entry, "mild")
    section = Section.from_polygon(
        corners=[(0.0, 0.0), (B, 0.0), (B, H), (0.0, H)],
        bars_xy_area_mm2=[(0.075, 0.05, 491.0), (0.225, 0.05, 491.0)],
    )
    table = fatigue_inputs.normalise_spectrum_table([
        {"spectrum": "S1", "name": "FAT-1", "cycles": 1.0e6,
         "mx_long_ed_knm": 100.0, "mx_short_ed_knm": 80.0},
        {"spectrum": "S2", "name": "FAT-2", "cycles": 1.0e6,
         "mx_long_ed_knm": 100.0, "mx_short_ed_knm": 55.0},
    ])
    inp = _steel_only_input(section=section, **{
        fatigue_inputs.SPECTRUM_TABLE_KEY: table,
    })
    inp["bar_elements"] = [
        {"id": "B-1", "x_mm": 75.0, "y_mm": 50.0, "area_mm2": 491.0,
         "diameter_mm": 25.0, "material_id": "B500",
         "fatigue_detail_id": "F1"},
        {"id": "B-2", "x_mm": 225.0, "y_mm": 50.0, "area_mm2": 491.0,
         "diameter_mm": 25.0, "material_id": "B500",
         "fatigue_detail_id": "F1"},
    ]
    inp["bar_materials"] = [steel, steel]
    inp.update(over)
    return inp


def _candidate(inp):
    """Reproduce the retained app fatigue publication (_run_fatigue_or_invalid)."""

    errors = fatigue_analysis.validation_errors(inp)
    payload = (fatigue_analysis.invalid_result(inp, errors) if errors
               else fatigue_analysis.run_analysis(inp))
    return {"fatigue": payload}


def _build(inp, out):
    return build_fatigue_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT)


def _bundle(inp, out=None):
    bundle = _build(inp, _candidate(inp) if out is None else out)
    assert bundle is not None
    return bundle


def _validate(bundle, inp, out):
    return validate_fatigue_trace_family(
        bundle, inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context=CONTEXT)


def _member_steps(bundle, suffix):
    for calculation in bundle.calculations:
        if calculation.calculation_id.endswith(suffix):
            return {step.step_id: step for step in calculation.steps}
    raise AssertionError(f"member {suffix} not published")


def _element_suffix(si, spectrum, ei, element_id, detail_id,
                    material_id="B500"):
    return (f"s{si:02d}-{trace_identity_token(spectrum)}-e{ei:02d}-"
            f"{trace_identity_token(element_id)}-"
            f"{trace_identity_token(material_id)}-"
            f"{trace_identity_token(detail_id)}")


def _with_result(out, si, ei, **changes):
    """Candidate copy with one reinforcement result field replaced."""

    payload = dict(out["fatigue"])
    spectra = list(payload["spectra"])
    result = spectra[si]
    reinforcement = list(result.reinforcement)
    reinforcement[ei] = dataclasses.replace(reinforcement[ei], **changes)
    spectra[si] = dataclasses.replace(
        result, reinforcement=tuple(reinforcement))
    payload["spectra"] = tuple(spectra)
    return {"fatigue": payload}


def _with_bin(out, si, ei, bi, **changes):
    result = out["fatigue"]["spectra"][si].reinforcement[ei]
    bins = list(result.bins)
    bins[bi] = dataclasses.replace(bins[bi], **changes)
    return _with_result(out, si, ei, bins=tuple(bins))


def _replaced_spectrum(payload, si, **changes):
    """Payload copy with one FatigueSpectrumResult field replaced."""

    spectra = list(payload["spectra"])
    spectra[si] = dataclasses.replace(spectra[si], **changes)
    return dict(payload, spectra=tuple(spectra))


def _with_state(out, si, bi, **changes):
    payload = dict(out["fatigue"])
    spectra = list(payload["spectra"])
    states = list(spectra[si].bins)
    states[bi] = dataclasses.replace(states[bi], **changes)
    spectra[si] = dataclasses.replace(spectra[si], bins=tuple(states))
    payload["spectra"] = tuple(spectra)
    return {"fatigue": payload}


# ---- closed-form oracles -----------------------------------------------------

def test_sn_life_closed_form_at_both_exponent_branches():
    inp = _steel_only_input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    steps = _member_steps(
        bundle, _element_suffix(0, "S1", 0, "B-1", "F1"))
    knee = RSK / GAMMA_S
    ranges = {
        "FAT-1": _sigma_mpa(180.0) - _sigma_mpa(100.0),  # above the knee
        "FAT-2": _sigma_mpa(120.0) - _sigma_mpa(100.0),  # below the knee
    }
    assert ranges["FAT-1"] >= knee > ranges["FAT-2"]
    for index, (name, expected_range) in enumerate(ranges.items()):
        prefix = bin_prefix(index, name)
        exponent, log10_life = _life_log10(expected_range)
        assert steps[f"{prefix}-stress-range"].result.value == pytest.approx(
            expected_range, rel=1e-6)
        assert steps[f"{prefix}-design-stress-range"].result.value == (
            pytest.approx(expected_range, rel=1e-6))
        assert steps[f"{prefix}-sn-exponent"].result.value == exponent
        assert steps[f"{prefix}-log10-cycles-to-failure"].result.value == (
            pytest.approx(log10_life, rel=1e-6))
    assert steps[f"{bin_prefix(0, 'FAT-1')}-sn-exponent"].result.value == K1
    assert steps[f"{bin_prefix(1, 'FAT-2')}-sn-exponent"].result.value == K2
    # The sealed values ARE the published bin results, bound exactly.
    result = out["fatigue"]["spectra"][0].reinforcement[0]
    for index, bin_result in enumerate(result.bins):
        prefix = bin_prefix(index, bin_result.bin_name)
        assert steps[f"{prefix}-damage"].result.value == bin_result.damage
        assert steps[f"{prefix}-log10-cycles-to-failure"].result.value == (
            bin_result.log10_cycles_to_failure)
    assert _validate(bundle, inp, out) is not None


def test_miner_accumulation_and_damage_limit_verdict():
    inp = _steel_only_input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    steps = _member_steps(bundle, _element_suffix(0, "S1", 0, "B-1", "F1"))
    result = out["fatigue"]["spectra"][0].reinforcement[0]
    # Closed-form Miner sum over both bins.
    expected = sum(
        cycles / 10.0 ** _life_log10(rng)[1]
        for cycles, rng in ((1.0e5, _sigma_mpa(180.0) - _sigma_mpa(100.0)),
                            (1.0e7, _sigma_mpa(120.0) - _sigma_mpa(100.0))))
    assert steps["damage-total"].result.value == pytest.approx(
        expected, rel=1e-6)
    assert steps["damage-total"].result.value == result.damage
    assert result.damage == sum(item.damage for item in result.bins)
    assert result.damage <= 1.0 and result.passed is True
    assert steps["passed"].result.value == STATUS_CODES["PASS"]
    assert steps["ct-010-element-result"].result.value == STATUS_CODES["PASS"]

    # Raising the applied cycles beyond the retained limit 1.0 fails.
    failing = _steel_only_input()
    table = failing[fatigue_inputs.SPECTRUM_TABLE_KEY]
    table.loc[0, "cycles"] = 1.0e12
    failing_out = _candidate(failing)
    failing_result = failing_out["fatigue"]["spectra"][0].reinforcement[0]
    assert failing_result.damage > 1.0
    assert failing_result.passed is False
    failing_steps = _member_steps(
        _bundle(failing, failing_out),
        _element_suffix(0, "S1", 0, "B-1", "F1"))
    assert failing_steps["passed"].result.value == STATUS_CODES["FAIL"]
    assert failing_steps["ct-010-element-result"].result.value == (
        STATUS_CODES["FAIL"])
    assert failing_out["fatigue"]["passed"] is False


def test_yield_screen_closed_form_and_governing_bins():
    inp = _steel_only_input()
    out = _candidate(inp)
    steps = _member_steps(_bundle(inp, out),
                          _element_suffix(0, "S1", 0, "B-1", "F1"))
    limit = 500.0 / GAMMA_S  # B500 tension branch
    utilisation = _sigma_mpa(180.0) / limit
    prefix = bin_prefix(0, "FAT-1")
    assert steps[f"{prefix}-yield-limit"].result.value == pytest.approx(limit)
    assert steps[f"{prefix}-yield-utilisation"].result.value == (
        pytest.approx(utilisation, rel=1e-6))
    # FAT-1 has the larger total action: it governs damage AND yield.
    assert steps["governing-damage-bin"].result.value == 0.0
    assert steps["governing-yield-bin"].result.value == 0.0
    result = out["fatigue"]["spectra"][0].reinforcement[0]
    assert result.governing_damage_bin == "FAT-1"
    assert result.governing_yield_bin == "FAT-1"
    assert steps["utilisation"].result.value == max(
        result.damage, result.yield_utilisation)
    assert steps["yield-utilisation"].result.value == (
        result.yield_utilisation)


def test_design_action_factor_scales_the_design_range_only():
    inp = _steel_only_input(fatigue_gamma_ff=1.25)
    out = _candidate(inp)
    steps = _member_steps(_bundle(inp, out),
                          _element_suffix(0, "S1", 0, "B-1", "F1"))
    prefix = bin_prefix(0, "FAT-1")
    characteristic = _sigma_mpa(180.0) - _sigma_mpa(100.0)
    design = _sigma_mpa(100.0 + 1.25 * 80.0) - _sigma_mpa(100.0)
    assert steps["input-gamma-ff"].result.value == 1.25
    assert steps[f"{prefix}-stress-range"].result.value == pytest.approx(
        characteristic, rel=1e-6)
    assert steps[f"{prefix}-design-stress-range"].result.value == (
        pytest.approx(design, rel=1e-6))
    # The life is entered with the design range; the knee stays gamma_s-only.
    exponent, log10_life = _life_log10(
        steps[f"{prefix}-design-stress-range"].result.value)
    assert steps[f"{prefix}-sn-exponent"].result.value == exponent
    assert steps[f"{prefix}-log10-cycles-to-failure"].result.value == (
        pytest.approx(log10_life, rel=1e-9))
    bin_result = out["fatigue"]["spectra"][0].reinforcement[0].bins[0]
    assert bin_result.design_stress_range_mpa > bin_result.stress_range_mpa


def test_long_only_bin_zero_range_corner_is_truthfully_annotated():
    # App-legitimate long-only bin: zero cyclic increment, zero design range.
    # The retained kernel returns exponent 0.0 WITHOUT evaluating the slope
    # branch; the sealed annotation must name that retained corner.
    table = fatigue_inputs.normalise_spectrum_table([
        {"spectrum": "S1", "name": "FAT-1", "cycles": 1.0e6,
         "mx_long_ed_knm": 100.0},
    ])
    inp = _steel_only_input(**{fatigue_inputs.SPECTRUM_TABLE_KEY: table})
    assert fatigue_analysis.validation_errors(inp) == []
    out = _candidate(inp)
    bin_result = out["fatigue"]["spectra"][0].reinforcement[0].bins[0]
    assert bin_result.design_stress_range_mpa == 0.0
    assert bin_result.sn_exponent == 0.0
    assert math.isinf(bin_result.log10_cycles_to_failure)
    assert bin_result.damage == 0.0
    bundle = _bundle(inp, out)
    steps = _member_steps(bundle, _element_suffix(0, "S1", 0, "B-1", "F1"))
    prefix = bin_prefix(0, "FAT-1")
    exponent = steps[f"{prefix}-sn-exponent"]
    assert exponent.result.state == RESULT_FINITE
    assert exponent.result.value == 0.0
    assert "k = 0" in exponent.actual_expression
    assert "delta_sigma_Ed = 0" in exponent.actual_expression
    life = steps[f"{prefix}-log10-cycles-to-failure"]
    assert life.result.state == RESULT_POSITIVE_INFINITY
    assert life.result.value is None
    assert steps[f"{prefix}-damage"].result.value == 0.0
    assert steps[f"{prefix}-bond-adjustment"].result.value == 1.0
    assert steps["passed"].result.value == STATUS_CODES["PASS"]
    assert _validate(bundle, inp, out) is not None


def test_mixed_bond_2005_eta_closed_form_and_perfect_bond():
    inp = _mixed_input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    tendon_detail = inp["tendon_elements"][0]["fatigue_detail_id"]
    eta = (982.0 + 1000.0) / (982.0 + 1000.0 * math.sqrt(0.5 * 25.0 / 40.0))
    bar_steps = _member_steps(bundle, _element_suffix(0, "S1", 0, "B-1", "F1"))
    tendon_steps = _member_steps(
        bundle, _element_suffix(0, "S1", 2, "T-1", tendon_detail,
                                material_id="P-1"))
    prefix = bin_prefix(0, "FAT-1")
    assert bar_steps[f"{prefix}-bond-adjustment"].result.value == (
        pytest.approx(eta, rel=1e-9))
    assert tendon_steps[f"{prefix}-bond-adjustment"].result.value == (
        pytest.approx(1.0, abs=1e-12))
    bar_bin = out["fatigue"]["spectra"][0].reinforcement[0].bins[0]
    assert "6.8.2(2)" in bar_bin.bond_method
    source = bar_steps[f"{prefix}-bond-adjustment"].source
    assert source == BOND_SOURCES[fatigue_inputs.EC2_2005]
    # Tendon-only bond leaves exist exactly on the tendon member.
    assert "detail-bond-xi" in tendon_steps
    assert tendon_steps["detail-bond-xi"].result.value == 0.5
    assert "detail-bond-xi" not in bar_steps
    # Non-mixed sections keep the retained perfect-bond identity.
    single = _steel_only_input()
    single_steps = _member_steps(
        _bundle(single), _element_suffix(0, "S1", 0, "B-1", "F1"))
    assert single_steps[f"{prefix}-bond-adjustment"].result.value == 1.0
    assert single_steps[f"{prefix}-bond-adjustment"].source == ADAPTER_SOURCE
    assert _validate(bundle, inp, out) is not None


def test_mixed_bond_2023_equivalent_area_identity():
    inp = _mixed_input(edition=fatigue_inputs.EC2_2023)
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    bar_bin = out["fatigue"]["spectra"][0].reinforcement[0].bins[0]
    assert "10.3(2)" in bar_bin.bond_method
    steps = _member_steps(bundle, _element_suffix(0, "S1", 0, "B-1", "F1"))
    prefix = bin_prefix(0, "FAT-1")
    assert steps[f"{prefix}-bond-adjustment"].source == (
        BOND_SOURCES[fatigue_inputs.EC2_2023])
    assert steps["input-edition"].result.value == float(
        EDITIONS.index(fatigue_inputs.EC2_2023))
    assert _validate(bundle, inp, out) is not None


def test_governing_selections_at_every_level():
    inp = _mixed_input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    payload = out["fatigue"]
    output = _member_steps(bundle, "-reinforcement-output")
    for si, (name, result) in enumerate(
            zip(("S1", "S2"), payload["spectra"])):
        ids = tuple(item.element_id for item in result.reinforcement)
        utils = [item.utilisation for item in result.reinforcement]
        assert result.governing_reinforcement_id == ids[utils.index(max(utils))]
        prefix = f"s{si:02d}-{trace_identity_token(name)}"
        assert output[f"{prefix}-governing-element"].result.value == (
            float(ids.index(result.governing_reinforcement_id)))
        # Steel-only run: the spectrum utilisation is reinforcement-derived.
        assert output[f"{prefix}-utilisation"].result.value == (
            result.utilisation)
        assert result.utilisation == max(utils)
    # S2 carries the larger cyclic action: it governs the family.
    assert payload["governing_spectrum"] == "S2"
    assert output["governing-spectrum"].result.value == 1.0
    assert output["family-utilisation"].result.value == payload["utilisation"]
    assert payload["utilisation"] == max(
        item.utilisation for item in payload["spectra"])
    assert output["ct-010-reinforcement-output-result"].result.value == (
        STATUS_CODES["PASS" if payload["passed"] else "FAIL"])
    assert _validate(bundle, inp, out) is not None


# ---- edition identity --------------------------------------------------------

def test_per_edition_sources_2005_dkna_2023():
    for edition, clause in ((fatigue_inputs.EC2_2005, "6.8.4"),
                            (fatigue_inputs.EC2_2005_DKNA, "6.8.4"),
                            (fatigue_inputs.EC2_2023, "E.5.2")):
        inp = _steel_only_input(fatigue_edition=edition)
        if "2023" in edition:
            catalogue = inp[fatigue_inputs.DETAIL_CATALOG_KEY]
            catalogue["items"][0] = fatigue_inputs.apply_preset(
                catalogue["items"][0], fatigue_inputs.PRESET_2023_BARS)
        out = _candidate(inp)
        assert fatigue_analysis.validation_errors(inp) == []
        steps = _member_steps(_bundle(inp, out),
                              _element_suffix(0, "S1", 0, "B-1", "F1"))
        source = steps[f"{bin_prefix(0, 'FAT-1')}-sn-exponent"].source
        assert source == SN_SOURCES[edition]
        assert source.citation.clause == clause
        assert source.edition == edition
        assert steps["input-edition"].result.value == float(
            EDITIONS.index(edition))
    dk = SN_SOURCES[fatigue_inputs.EC2_2005_DKNA]
    assert "DK NA:2024" in dk.citation.document
    assert "6.3N/6.4N" in SN_SOURCES[fatigue_inputs.EC2_2005].citation.locator
    assert "E.1/E.2" in SN_SOURCES[fatigue_inputs.EC2_2023].citation.locator


def test_2023_materials_never_finite_but_2023_edition_is_legitimate():
    entry = mat_catalog.default_entry(
        "mild", material_id="B500", preset=codes.EC2_2023.label)
    inp = _steel_only_input()
    inp["bar_materials"] = [mat_catalog.build_material(entry, "mild")]
    inp[mat_catalog.MILD_CATALOG_KEY] = {
        "version": 1, "next_id": 2, "items": [entry]}
    assert fatigue_analysis.validation_errors(inp) == []
    with pytest.raises(TraceValidationError, match="2023 material"):
        _build(inp, _candidate(inp))
    # The invalid branch stays a legitimate failed state whatever material
    # edition is assigned: branch selection from direct inputs first.
    invalid = copy.copy(inp)
    invalid["fatigue_gamma_s"] = 0.0
    invalid_out = _candidate(invalid)
    assert invalid_out["fatigue"]["valid"] is False
    assert _build(invalid, invalid_out) is not None
    # Unknown editions are the retained fail-closed invalid branch.
    unknown = _steel_only_input(fatigue_edition="EN 1993-1-9")
    unknown_out = _candidate(unknown)
    assert unknown_out["fatigue"]["valid"] is False
    bundle = _build(unknown, unknown_out)
    assert bundle.calculations[0].steps[-1].result.state == RESULT_FAILED


# ---- invalid branch ----------------------------------------------------------

def test_invalid_branch_error_classes_payload_and_valid_key_pin():
    variants = (
        ({"bar_detail": ""}, "B-1: fatigue detail ID is required"),
        ({"fatigue_gamma_s": -1.0},
         "gamma_s must be a finite number greater than zero"),
        ({fatigue_inputs.SPECTRUM_TABLE_KEY:
          fatigue_inputs.empty_spectrum_table()},
         "At least one fatigue spectrum bin is required"),
    )
    for overrides, message in variants:
        inp = _steel_only_input(
            **{k: v for k, v in overrides.items() if k != "bar_detail"})
        if "bar_detail" in overrides:
            inp["bar_elements"][0]["fatigue_detail_id"] = ""
        out = _candidate(inp)
        payload = out["fatigue"]
        assert tuple(payload) == INVALID_KEYS
        assert tuple(payload)[0] == "valid" and payload["valid"] is False
        assert message in payload["errors"]
        bundle = _bundle(inp, out)
        assert len(bundle.calculations) == 1
        calculation = bundle.calculations[0]
        assert calculation.calculation_id.endswith("-invalid")
        final = calculation.steps[-1]
        assert final.result.state == RESULT_FAILED
        assert final.result.value is None
        assert message in final.result.reason
        # Every retained error message is tokenized into a sealed step id.
        for error in payload["errors"]:
            token = trace_identity_token(error)
            assert any(token in step.step_id for step in calculation.steps)
        assert _validate(bundle, inp, out) is not None
        # The pinned asymmetry: no normalisation in either direction.
        stripped = {"fatigue": {key: value for key, value
                                in payload.items() if key != "valid"}}
        with pytest.raises(TraceValidationError):
            _build(inp, stripped)
        promoted = {"fatigue": dict(payload, valid=True)}
        with pytest.raises(TraceValidationError):
            _build(inp, promoted)
        # A tampered retained error identity reseals differently.
        forged = {"fatigue": dict(
            payload, errors=tuple(list(payload["errors"])[:-1] or ("x",)))}
        with pytest.raises(TraceValidationError):
            _build(inp, forged)
    # The valid payload can never carry the invalid-branch valid key.
    valid_inp = _steel_only_input()
    valid_out = _candidate(valid_inp)
    assert "valid" not in valid_out["fatigue"]
    injected = {"fatigue": {"valid": False, **valid_out["fatigue"]}}
    with pytest.raises(TraceValidationError):
        _build(valid_inp, injected)


def test_invalid_bundle_is_stale_against_the_fixed_input():
    broken = _steel_only_input(fatigue_gamma_s=0.0)
    broken_out = _candidate(broken)
    invalid_bundle = _bundle(broken, broken_out)
    fixed = _steel_only_input()
    fixed_out = _candidate(fixed)
    with pytest.raises(TraceValidationError):
        _validate(invalid_bundle, fixed, fixed_out)
    with pytest.raises(TraceValidationError):
        _validate(_bundle(fixed, fixed_out), broken, broken_out)


# ---- applicability and fencing -----------------------------------------------

def test_check_steel_off_publishes_no_members_and_candidates_fail():
    inp = _steel_only_input(
        fatigue_check_steel=False, fatigue_check_concrete=True,
        fatigue_gamma_c=1.5, fatigue_beta_cc_t0=1.0, fatigue_t0_days=28.0,
        fatigue_concrete_k1=0.85, fatigue_concrete_c=14.0,
    )
    out = _candidate(inp)
    payload = out["fatigue"]
    assert fatigue_analysis.validation_errors(inp) == []
    assert payload["checks"]["reinforcement"] is False
    assert payload["reinforcement_properties"] == ()
    assert payload["spectra"][0].reinforcement == ()
    assert payload["spectra"][0].governing_reinforcement_id is None
    assert _build(inp, out) is None
    assert _validate(None, inp, out) is None
    # A supplied candidate bundle fails on this member state.
    other = _bundle(_steel_only_input())
    with pytest.raises(TraceValidationError):
        _validate(other, inp, out)
    # Fabricated reinforcement evidence on the concrete-only branch fails.
    fabricated = dict(payload)
    fabricated["reinforcement_properties"] = (
        _candidate(_steel_only_input())["fatigue"]
        ["reinforcement_properties"])
    with pytest.raises(TraceValidationError):
        _build(inp, {"fatigue": fabricated})


def _joint_input():
    """Both checks enabled on a moderate spectrum: joint utilisation must be
    FINITE so the exact-closure forgery probes are non-vacuous (with the
    standard steel spectrum the concrete damage is +inf and inf + 0.01 == inf
    would pass the exact comparator)."""

    table = fatigue_inputs.normalise_spectrum_table([
        {"spectrum": "S1", "name": "FAT-1", "cycles": 1.0e5,
         "mx_long_ed_knm": 50.0, "mx_short_ed_knm": 40.0},
    ])
    return _steel_only_input(
        fatigue_check_concrete=True, fatigue_gamma_c=1.5,
        fatigue_beta_cc_t0=1.0, fatigue_t0_days=28.0,
        fatigue_concrete_k1=0.85, fatigue_concrete_c=14.0,
        **{fatigue_inputs.SPECTRUM_TABLE_KEY: table},
    )


def test_joint_run_output_shape_forgeries_and_concrete_boundary():
    inp = _joint_input()
    out = _candidate(inp)
    payload = out["fatigue"]
    assert fatigue_analysis.validation_errors(inp) == []
    assert payload["checks"] == {"reinforcement": True, "concrete": True}
    assert math.isfinite(payload["utilisation"])
    assert payload["converged"] is True and payload["passed"] is True
    bundle = _bundle(inp, out)
    assert len(bundle.calculations) == 2  # 1 element member + output
    output_calc = next(c for c in bundle.calculations
                       if c.calculation_id.endswith("-reinforcement-output"))
    step_ids = {step.step_id for step in output_calc.steps}
    # joint=True: the steel-only family selection steps are ABSENT (the
    # joint top-level fields depend on the excluded concrete siblings).
    assert "governing-spectrum" not in step_ids
    assert "family-utilisation" not in step_ids
    assert f"s00-{trace_identity_token('S1')}-utilisation" not in step_ids
    assert f"s00-{trace_identity_token('S1')}-governing-element" in step_ids
    assert {"reinforcement-converged", "reinforcement-passed"} < step_ids
    axes = {axis.name: axis.value for axis in output_calc.axes}
    assert axes["joint"] == "true"
    assert _validate(bundle, inp, out) is not None
    # The four surface-validated top-level fields stay bound exactly even
    # though they are not sealed as steps on the joint branch.
    for key, value in (("utilisation", payload["utilisation"] + 0.01),
                       ("converged", False),
                       ("passed", False),
                       ("governing_spectrum", "S9")):
        forged = dict(payload)
        forged[key] = value
        with pytest.raises(TraceValidationError):
            _build(inp, {"fatigue": forged})
    # Concrete siblings on a payload that actually carries concrete results:
    # a VALUE swap stays inert (named PR-08D.3b exclusion)...
    spectrum = payload["spectra"][0]
    assert type(spectrum.fcd_fat_mpa) is float
    assert len(spectrum.concrete) > 0
    inert = _replaced_spectrum(
        payload, 0, fcd_fat_mpa=spectrum.fcd_fat_mpa + 5.0)
    assert _build(inp, {"fatigue": inert}) is not None
    relabeled = dict(payload, concrete_parameters={"tampered": 1.0})
    assert _build(inp, {"fatigue": relabeled}) is not None
    relabeled = dict(payload, concrete_method="tampered concrete method")
    assert _build(inp, {"fatigue": relabeled}) is not None
    for key in ("concrete_method", "concrete_parameters"):
        retyped = dict(payload)
        retyped[key] = []
        with pytest.raises(TraceValidationError, match="retained type"):
            _build(inp, {"fatigue": retyped})
    # ...while a TYPE swap on the same siblings fails closed.
    for changes in ({"fcd_fat_mpa": None}, {"concrete_search": None},
                    {"concrete": list(spectrum.concrete)}):
        with pytest.raises(TraceValidationError):
            _build(inp, {"fatigue": _replaced_spectrum(
                payload, 0, **changes)})


def test_fatigue_off_and_section_fence_are_absence_states():
    disabled = _steel_only_input(fatigue_on=False)
    assert _build(disabled, {}) is None
    assert _validate(None, disabled, {}) is None
    with pytest.raises(TraceValidationError, match="inactive"):
        _build(disabled, {"fatigue": None})
    with pytest.raises(TraceValidationError, match="inactive"):
        _build(disabled, _candidate(_steel_only_input()))
    absent = _steel_only_input()
    del absent["fatigue_on"]
    assert _build(absent, {}) is None
    # The retained run_analysis publishes no fatigue surface on a broken
    # section run: the family is fenced, not invalid.
    fenced = _steel_only_input(geometry_error="outline is self-intersecting")
    assert _build(fenced, {}) is None
    with pytest.raises(TraceValidationError, match="inactive"):
        _build(fenced, _candidate(_steel_only_input()))
    # An active input demands its published surface.
    active = _steel_only_input()
    with pytest.raises(TraceValidationError, match="must publish"):
        _build(active, {})
    # A stale bundle against the disabled input fails closed.
    bundle = _bundle(_steel_only_input())
    with pytest.raises(TraceValidationError):
        _validate(bundle, disabled, {})


def test_exact_input_typing_is_enforced():
    base_out = _candidate(_steel_only_input())
    for changes, match in (
        ({"fatigue_on": 1}, "Boolean"),
        ({"fatigue_on": "yes"}, "Boolean"),
        ({"fatigue_check_steel": 1}, "Boolean"),
        ({"fatigue_check_concrete": "no"}, "Boolean"),
        ({"nl": "6.0"}, "number"),
        ({"fatigue_gamma_s": True}, "number"),
        ({"fatigue_gamma_ff": "1.0"}, "number"),
    ):
        with pytest.raises(TraceValidationError, match=match):
            _build(_steel_only_input(**changes), base_out)


# ---- retained non-finite and non-converged states -----------------------------

def _flip_convergence(monkeypatch, marker):
    original = fatigue_mod.solve_elastic_combined

    def wrapper(section, p_l, mx_l, my_l, nl, p_s, mx_s, my_s, ns, **kwargs):
        result = original(section, p_l, mx_l, my_l, nl, p_s, mx_s, my_s, ns,
                          **kwargs)
        if math.isclose(mx_s, marker, rel_tol=0.0, abs_tol=1.0e-9):
            return dataclasses.replace(result, converged=False)
        return result

    monkeypatch.setattr(fatigue_mod, "solve_elastic_combined", wrapper)


def test_non_converged_bin_is_retained_evidence_never_promoted(monkeypatch):
    inp = _two_element_input()
    _flip_convergence(monkeypatch, 55.0)
    out = _candidate(inp)
    payload = out["fatigue"]
    assert payload["converged"] is False
    assert payload["passed"] is False
    assert payload["spectra"][0].converged is True
    assert payload["spectra"][1].converged is False
    bundle = _bundle(inp, out)
    steps = _member_steps(bundle, _element_suffix(1, "S2", 0, "B-1", "F1"))
    prefix = bin_prefix(0, "FAT-2")
    assert steps[f"{prefix}-upstream-converged"].result.value == 0.0
    assert steps["converged"].result.value == 0.0
    assert steps["passed"].result.value == STATUS_CODES["FAIL"]
    # The retained kernel still publishes the bin numerics; they are bound
    # truthfully, never fail-closed on retained-published values.
    assert steps[f"{prefix}-damage"].result.state == RESULT_FINITE
    output = _member_steps(bundle, "-reinforcement-output")
    assert output["reinforcement-converged"].result.value == 0.0
    assert output["ct-010-reinforcement-output-result"].result.value == (
        STATUS_CODES["FAIL"])
    assert _validate(bundle, inp, out) is not None
    # Promotion: a candidate claiming convergence fails against the replay.
    promoted = _with_state(
        _with_bin(out, 1, 0, 0, converged=True), 1, 0, converged=True)
    with pytest.raises(TraceValidationError):
        _build(inp, promoted)


def test_infinite_retained_damage_seals_positive_infinity():
    inp = _steel_only_input()
    catalogue = inp[fatigue_inputs.DETAIL_CATALOG_KEY]
    catalogue["items"][0]["delta_sigma_rsk_mpa"] = 1.0e-60  # custom detail
    inp[fatigue_inputs.DETAIL_CATALOG_KEY] = (
        fatigue_inputs.normalise_catalog(catalogue))
    assert fatigue_analysis.validation_errors(inp) == []
    out = _candidate(inp)
    payload = out["fatigue"]
    result = payload["spectra"][0].reinforcement[0]
    assert math.isinf(result.damage) and result.damage > 0.0
    assert math.isinf(payload["utilisation"])
    assert result.passed is False
    bundle = _bundle(inp, out)
    steps = _member_steps(
        bundle,
        _element_suffix(0, "S1", 0, "B-1", "F1"))
    damage = steps[f"{bin_prefix(0, 'FAT-1')}-damage"]
    assert damage.result.state == RESULT_POSITIVE_INFINITY
    assert damage.result.value is None
    assert "unbounded" in damage.result.reason
    assert steps["damage-total"].result.state == RESULT_POSITIVE_INFINITY
    assert steps["utilisation"].result.state == RESULT_POSITIVE_INFINITY
    assert steps["passed"].result.value == STATUS_CODES["FAIL"]
    assert steps["ct-010-element-result"].result.state == RESULT_FINITE
    output = _member_steps(bundle, "-reinforcement-output")
    assert output["family-utilisation"].result.state == (
        RESULT_POSITIVE_INFINITY)
    payload_json = bundle_to_json(bundle)
    assert "Infinity" not in payload_json and "NaN" not in payload_json
    assert _validate(bundle, inp, out) is not None


def test_divergent_engine_fails_closed_never_relabeled(monkeypatch):
    # Upstream boundary control: the sealed engine-evidence leaves consume
    # the PUBLISHED payload, exactly cross-checked against the replay. A
    # divergent engine (kernel or solver) must fail the build closed rather
    # than seal relabeled values under the evidence source.
    inp = _steel_only_input()
    out = _candidate(inp)  # published with the shipped engine
    assert _build(inp, out) is not None

    original_life = fatigue_mod.steel_fatigue_life

    def divergent_life(stress_range_mpa, **kwargs):
        return original_life(stress_range_mpa * 1.001, **kwargs)

    monkeypatch.setattr(fatigue_mod, "steel_fatigue_life", divergent_life)
    with pytest.raises(TraceValidationError):
        _build(inp, out)
    monkeypatch.setattr(fatigue_mod, "steel_fatigue_life", original_life)

    original_solve = fatigue_mod.solve_elastic_combined

    def divergent_solve(*args, **kwargs):
        result = original_solve(*args, **kwargs)
        return dataclasses.replace(
            result, bar_stress_total=tuple(
                value * 1.0001 for value in result.bar_stress_total))

    monkeypatch.setattr(fatigue_mod, "solve_elastic_combined",
                        divergent_solve)
    with pytest.raises(TraceValidationError):
        _build(inp, out)


def test_engine_evidence_labeling_is_leaf_only_and_published():
    # Every engine-evidence step is a dependency-free method-value leaf whose
    # sealed value IS the published payload field; every recomputed step
    # carries a truthful project or standards source, never engine evidence.
    from sector.calculation_trace import ROLE_METHOD_VALUE
    from sector.fatigue_trace_contract import ENGINE_SOURCE

    inp = _steel_only_input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    steps = _member_steps(bundle, _element_suffix(0, "S1", 0, "B-1", "F1"))
    engine_steps = {step_id: step for step_id, step in steps.items()
                    if step.source == ENGINE_SOURCE}
    assert engine_steps and all(
        step.quantity_role == ROLE_METHOD_VALUE and not step.dependencies
        for step in engine_steps.values())
    assert set(engine_steps) == {
        f"{bin_prefix(index, name)}-upstream-{suffix}"
        for index, name in enumerate(("FAT-1", "FAT-2"))
        for suffix in ("converged", "stress-long", "stress-total",
                       "stress-total-elastic", "stress-total-design")}
    result = out["fatigue"]["spectra"][0].reinforcement[0]
    for index, bin_result in enumerate(result.bins):
        prefix = bin_prefix(index, bin_result.bin_name)
        assert steps[f"{prefix}-upstream-stress-long"].result.value == (
            bin_result.stress_long_mpa)
        assert steps[f"{prefix}-upstream-stress-total"].result.value == (
            bin_result.stress_total_mpa)
        assert steps[
            f"{prefix}-upstream-stress-total-design"].result.value == (
            bin_result.stress_total_design_mpa)
    for step_id, step in steps.items():
        if step.quantity_role in (ROLE_COMPUTED, ROLE_FINAL):
            assert step.source != ENGINE_SOURCE, step_id


def test_nonfinite_sealing_unit_probe():
    # The negative-infinity and NaN paths guard retained-published values not
    # reachable through the shipped kernels; they represent, never fabricate.
    rows = _Rows()
    rows.add("input-check-steel", "Reinforcement fatigue check enabled", ONE,
             ROLE_USER_INPUT, INPUT_SOURCE)
    rows.add("unbounded", "Unbounded retained value", MM, ROLE_COMPUTED,
             ADAPTER_SOURCE, "input-check-steel")
    rows.add("negative-unbounded", "Negative unbounded retained value", MM,
             ROLE_COMPUTED, ADAPTER_SOURCE, "input-check-steel")
    rows.add("undefined", "Undefined retained value", MM, ROLE_COMPUTED,
             ADAPTER_SOURCE, "input-check-steel")
    rows.add("mini-final", "Mini final state", ONE, ROLE_FINAL,
             ADAPTER_SOURCE, "unbounded", "negative-unbounded", "undefined")
    calculation = _calculation(
        "ct-010-mini", "Sealing probe", (), tuple(rows.rows),
        {"input-check-steel": 1.0, "unbounded": math.inf,
         "negative-unbounded": -math.inf, "undefined": math.nan,
         "mini-final": 1.0})
    by_id = {step.step_id: step for step in calculation.steps}
    assert by_id["unbounded"].result.state == RESULT_POSITIVE_INFINITY
    assert by_id["negative-unbounded"].result.state == (
        RESULT_NEGATIVE_INFINITY)
    assert by_id["undefined"].result.state == RESULT_UNDEFINED
    assert by_id["undefined"].result.value is None
    assert "undefined" in by_id["undefined"].result.reason
    assert by_id["mini-final"].result.state == RESULT_FINITE


# ---- exact closure, mutation and identity --------------------------------------

def test_exact_closure_rejects_sub_tolerance_perturbations():
    inp = _steel_only_input()
    out = _candidate(inp)
    assert _build(inp, out) is not None
    result = out["fatigue"]["spectra"][0].reinforcement[0]
    # A tolerant comparator would accept both of these; exact closure must not.
    for changed in (
        _with_bin(out, 0, 0, 0,
                  damage=result.bins[0].damage * (1.0 + 1.0e-12)),
        _with_bin(out, 0, 0, 0,
                  stress_long_mpa=result.bins[0].stress_long_mpa + 1.0e-9),
        _with_result(out, 0, 0,
                     utilisation=result.utilisation * (1.0 + 1.0e-13)),
    ):
        with pytest.raises(TraceValidationError):
            _build(inp, changed)


def test_bin_and_result_field_sweep_rejects_every_mutation():
    inp = _steel_only_input()
    out = _candidate(inp)
    result = out["fatigue"]["spectra"][0].reinforcement[0]

    def mutated(value):
        if type(value) is bool:
            return not value
        if type(value) is float:
            return value + 0.271828
        if type(value) is str:
            return value + "-tampered"
        raise AssertionError(f"unexpected field type {type(value)!r}")

    for name in BIN_RESULT_FIELDS:
        changed = _with_bin(out, 0, 0, 0,
                            **{name: mutated(getattr(result.bins[0], name))})
        with pytest.raises(TraceValidationError):
            _build(inp, changed)
    for name in RESULT_FIELDS:
        if name == "bins":
            for operation in ("pop", "duplicate", "reverse"):
                bins = list(result.bins)
                if operation == "pop":
                    bins.pop()
                elif operation == "duplicate":
                    bins.append(bins[0])
                else:
                    bins.reverse()
                with pytest.raises(TraceValidationError):
                    _build(inp, _with_result(out, 0, 0, bins=tuple(bins)))
            continue
        changed = _with_result(out, 0, 0,
                               **{name: mutated(getattr(result, name))})
        with pytest.raises(TraceValidationError):
            _build(inp, changed)
    # Consumed engine bin-state leaves reject mutation and cardinality drift.
    state = out["fatigue"]["spectra"][0].bins[0]
    for changed in (
        _with_state(out, 0, 0, bar_stress_long_mpa=tuple(
            value + 1.0 for value in state.bar_stress_long_mpa)),
        _with_state(out, 0, 0, bar_stress_fatigue_total_mpa=()),
        _with_state(out, 0, 0, bond_method="tampered"),
        _with_state(out, 0, 0, design_action_factor=1.1),
    ):
        with pytest.raises(TraceValidationError):
            _build(inp, changed)


def test_concrete_side_keys_are_named_excluded_siblings():
    inp = _steel_only_input()
    out = _candidate(inp)
    state = out["fatigue"]["spectra"][0].bins[0]
    # Value-level tampering of the excluded concrete stresses does NOT fail
    # this slice: those members are PR-08D.3b. Type/shape stays pinned.
    excluded = _with_state(out, 0, 0, concrete_compression_long_mpa=tuple(
        value + 1.0 for value in state.concrete_compression_long_mpa))
    assert _build(inp, excluded) is not None
    # A type-level swap on an excluded sibling still fails closed.
    retyped = _with_state(out, 0, 0, concrete_compression_long_mpa=None)
    with pytest.raises(TraceValidationError):
        _build(inp, retyped)
    payload = dict(out["fatigue"])
    spectra = list(payload["spectra"])
    spectra[0] = dataclasses.replace(spectra[0], fcd_fat_mpa=25.0)
    payload["spectra"] = tuple(spectra)
    with pytest.raises(TraceValidationError):
        _build(inp, {"fatigue": payload})
    assert set(("concrete_method", "concrete_parameters")) < set(VALID_KEYS)
    # The excluded values stay outside this slice, but their retained types
    # are part of the frozen boundary on both the steel-only and joint paths.
    for key in ("concrete_method", "concrete_parameters"):
        retyped = dict(out["fatigue"])
        retyped[key] = []
        with pytest.raises(TraceValidationError, match="retained type"):
            _build(inp, {"fatigue": retyped})


def test_top_level_payload_inventory_walk():
    inp = _steel_only_input()
    out = _candidate(inp)
    payload = out["fatigue"]
    assert tuple(payload) == VALID_KEYS
    # Removing, adding, or reordering retained keys fails at every layer.
    for key in VALID_KEYS:
        missing = dict(payload)
        del missing[key]
        with pytest.raises(TraceValidationError):
            _build(inp, {"fatigue": missing})
    extra = dict(payload)
    extra["unexpected-ct010-key"] = 0.0
    with pytest.raises(TraceValidationError):
        _build(inp, {"fatigue": extra})
    reordered = dict(reversed(list(payload.items())))
    with pytest.raises(TraceValidationError):
        _build(inp, {"fatigue": reordered})
    # Scalar and mapping surfaces owned by this slice are bound exactly.
    mutations = (
        ("edition", "DS/EN 1992-1-1:2023"),
        ("checks", {"reinforcement": True, "concrete": True}),
        ("checks", {"concrete": False, "reinforcement": True}),
        ("basis", {"method": "Grouped action spectrum", "notes": "x"}),
        ("method_reference", "tampered"),
        ("warnings", ("fabricated warning",)),
        ("partial_factors",
         {"gamma_c": None, "gamma_s": 1.2, "gamma_ff": 1.0}),
        ("governing_spectrum", "S9"),
        ("utilisation", payload["utilisation"] + 0.01),
        ("converged", False),
        ("passed", False),
        ("t0_days", 28.0),
        ("elements", ()),
        ("fatigue_detail_basis", ()),
        ("reinforcement_properties", ()),
    )
    for key, value in mutations:
        changed = dict(payload)
        changed[key] = value
        with pytest.raises(TraceValidationError):
            _build(inp, {"fatigue": changed})
    # Reinforcement properties are bound field-exactly (identity included).
    props = payload["reinforcement_properties"][0]
    for name, value in (("detail_id", "F9"), ("n_star", props.n_star * 2.0),
                        ("fytk_mpa", props.fytk_mpa + 1.0)):
        changed = dict(payload)
        changed["reinforcement_properties"] = (
            dataclasses.replace(props, **{name: value}),)
        with pytest.raises(TraceValidationError):
            _build(inp, {"fatigue": changed})


def _walk(value, path=()):
    if isinstance(value, Mapping):
        yield "mapping", path, tuple(value)
        for key in value:
            yield from _walk(value[key], (*path, key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _walk(item, (*path, index))
    else:
        yield "leaf", path, value


def _at(value, path):
    for key in path:
        value = value[key]
    return value


def _replaced(node, path, value):
    """Functional deep replacement that survives immutable tuple containers."""

    if not path:
        return value
    key = path[0]
    if isinstance(node, Mapping):
        out = dict(node)
        out[key] = _replaced(node[key], path[1:], value)
        return out
    items = list(node)
    items[key] = _replaced(node[key], path[1:], value)
    return type(node)(items)


def _mutated_leaf(value):
    if type(value) is bool:
        return not value
    if type(value) is int:
        return value + 1
    if isinstance(value, float):
        return value + 0.271828
    if isinstance(value, str):
        return value + "-tampered"
    return 0.0  # None leaves become a fabricated numeric


def test_invalid_payload_inventory_walk():
    inp = _steel_only_input(fatigue_gamma_ff=-2.0)
    inp["bar_elements"][0]["fatigue_detail_id"] = ""
    out = _candidate(inp)
    payload = out["fatigue"]
    assert payload["valid"] is False and len(payload["errors"]) >= 2
    assert _build(inp, out) is not None
    for kind, path, detail in list(_walk(payload)):
        if kind == "leaf":
            changed = _replaced(payload, list(path), _mutated_leaf(detail))
            with pytest.raises(TraceValidationError):
                _build(inp, {"fatigue": changed})
            continue
        node = _at(payload, path) if path else payload
        variants = [dict(node, **{"unexpected-ct010-field": 0.0})]
        variants.extend(
            {key: value for key, value in node.items() if key != removed}
            for removed in detail)
        if len(detail) > 1:
            variants.append(dict(reversed(list(node.items()))))
        for variant in variants:
            changed = _replaced(payload, list(path), variant)
            with pytest.raises(TraceValidationError):
                _build(inp, {"fatigue": changed})


def test_same_curve_different_detail_id_reseals_differently():
    inp = _steel_only_input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    renamed = _steel_only_input()
    catalogue, new_id = fatigue_inputs.duplicate_entry(
        renamed[fatigue_inputs.DETAIL_CATALOG_KEY], "F1")
    renamed[fatigue_inputs.DETAIL_CATALOG_KEY] = catalogue
    renamed["bar_elements"][0]["fatigue_detail_id"] = new_id
    assert fatigue_analysis.validation_errors(renamed) == []
    renamed_out = _candidate(renamed)
    # Identical S-N curve values, different detail identity: stale candidate
    # payloads and stale bundles both fail; the new bundle seals differently.
    with pytest.raises(TraceValidationError):
        _build(renamed, out)
    renamed_bundle = _bundle(renamed, renamed_out)
    assert renamed_bundle.to_dict() != bundle.to_dict()
    with pytest.raises(TraceValidationError):
        _validate(bundle, renamed, renamed_out)
    token = trace_identity_token(new_id)
    assert any(token in calculation.calculation_id
               for calculation in renamed_bundle.calculations)


def test_same_law_different_material_id_reseals_differently():
    inp = _steel_only_input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    renamed = _steel_only_input()
    entry = renamed[mat_catalog.MILD_CATALOG_KEY]["items"][0]
    twin = dict(entry, id="B500-alt")  # identical law, different identity
    renamed[mat_catalog.MILD_CATALOG_KEY] = {
        "version": 1, "next_id": 3, "items": [entry, twin]}
    renamed["bar_elements"][0] = dict(renamed["bar_elements"][0],
                                      material_id="B500-alt")
    assert fatigue_analysis.validation_errors(renamed) == []
    renamed_out = _candidate(renamed)
    renamed_bundle = _bundle(renamed, renamed_out)
    # Same-law different-material-ID assignments seal differently: the
    # material identity is tokenized into the sealed calculation ids.
    assert renamed_bundle.to_dict() != bundle.to_dict()
    token = trace_identity_token("B500-alt")
    assert any(token in calculation.calculation_id
               for calculation in renamed_bundle.calculations)
    with pytest.raises(TraceValidationError):
        _validate(bundle, renamed, renamed_out)
    with pytest.raises(TraceValidationError):
        _validate(renamed_bundle, inp, out)


def test_same_law_different_concrete_material_id_reseals_differently():
    inp = _steel_only_input(concrete_material_id="C30-A")
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    renamed = _steel_only_input(concrete_material_id="C30-B")
    renamed_out = _candidate(renamed)
    # The concrete law and retained fatigue result are unchanged; the
    # immutable material assignment identity must still seal differently.
    assert renamed_out["fatigue"] == out["fatigue"]
    renamed_bundle = _bundle(renamed, renamed_out)
    assert renamed_bundle.to_dict() != bundle.to_dict()
    token = trace_identity_token("C30-B")
    assert any(token in step.step_id
               for calculation in renamed_bundle.calculations[:-1]
               for step in calculation.steps)
    with pytest.raises(TraceValidationError):
        _validate(bundle, renamed, renamed_out)
    with pytest.raises(TraceValidationError):
        _validate(renamed_bundle, inp, out)


def test_published_bin_description_identity_reseals_differently():
    inp = _steel_only_input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    renamed = _steel_only_input()
    table = renamed[fatigue_inputs.SPECTRUM_TABLE_KEY].copy(deep=True)
    table.loc[0, "description"] = "Published fatigue bin description"
    renamed[fatigue_inputs.SPECTRUM_TABLE_KEY] = table
    renamed_out = _candidate(renamed)
    assert renamed_out["fatigue"] != out["fatigue"]
    renamed_bundle = _bundle(renamed, renamed_out)
    assert renamed_bundle.to_dict() != bundle.to_dict()
    token = trace_identity_token("Published fatigue bin description")
    assert any(token in step.step_id
               for calculation in renamed_bundle.calculations[:-1]
               for step in calculation.steps)
    with pytest.raises(TraceValidationError):
        _validate(bundle, renamed, renamed_out)
    with pytest.raises(TraceValidationError):
        _validate(renamed_bundle, inp, out)


def test_element_member_seals_immutable_geometry_and_material_vectors():
    bundle = _bundle(_steel_only_input(concrete_material_id="C30-A"))
    calculation = bundle.calculations[0]
    by_id = {step.step_id: step for step in calculation.steps}
    normalised = by_id["normalised-fatigue-inputs"]
    dependencies = {dependency.step_id for dependency in normalised.dependencies}
    assert {"geometry-vector", "material-vector"} < dependencies
    assert any(step_id.startswith("geometry-ring-") for step_id in by_id)
    assert any(step_id.startswith("geometry-bar-") for step_id in by_id)
    concrete = trace_identity_token("C30-A")
    assert any(step_id.startswith("material-concrete-") and concrete in step_id
               for step_id in by_id)


def test_element_and_spectrum_identity_tokens_and_renames():
    inp = _mixed_input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    steps = _member_steps(bundle, "-reinforcement-output")
    for name in ("S1", "S2"):
        token = trace_identity_token(name)
        assert any(token in step_id for step_id in steps)
    for element_id in ("B-1", "B-2", "T-1"):
        token = trace_identity_token(element_id)
        assert any(token in step_id for step_id in steps)
    renamed = _mixed_input()
    renamed["bar_elements"][0] = dict(renamed["bar_elements"][0], id="B-9")
    renamed_out = _candidate(renamed)
    assert fatigue_analysis.validation_errors(renamed) == []
    with pytest.raises(TraceValidationError):
        _build(renamed, out)  # stale candidate identity
    with pytest.raises(TraceValidationError):
        _validate(bundle, renamed, renamed_out)


def test_resealed_value_source_unit_axes_order_method_tampers():
    inp = _mixed_input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    target = next(c for c in bundle.calculations
                  if c.calculation_id.endswith("-reinforcement-output"))

    def _retarget(**changes):
        return seal_bundle(dataclasses.replace(
            bundle, calculations=tuple(
                dataclasses.replace(c, **changes) if c is target else c
                for c in bundle.calculations)))

    steps = list(target.steps)
    index = next(i for i, s in enumerate(steps)
                 if s.step_id == "family-utilisation")
    value_steps = list(steps)
    value_steps[index] = dataclasses.replace(
        steps[index], result=dataclasses.replace(
            steps[index].result, value=steps[index].result.value + 0.01))
    source_steps = list(steps)
    source_steps[index] = dataclasses.replace(
        steps[index], source=ADAPTER_SOURCE)
    wrong = TraceUnit("kN", "force")
    unit_steps = tuple(dataclasses.replace(
        step, unit=wrong if step.step_id == "family-utilisation"
        else step.unit,
        dependencies=tuple(TraceDependency(
            dep.step_id,
            wrong if dep.step_id == "family-utilisation" else dep.unit)
            for dep in step.dependencies)) for step in steps)
    swapped = list(steps)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    axes_tamper = _retarget(axes=tuple(
        dataclasses.replace(axis, value="true" if axis.value == "false"
                            else "false")
        if axis.name == "joint" else axis for axis in target.axes))
    for candidate in (
        _retarget(steps=tuple(value_steps)),
        _retarget(steps=tuple(source_steps)),
        _retarget(steps=unit_steps),
        _retarget(steps=tuple(swapped)),
        _retarget(method_id="wrong-fatigue-method"),
        axes_tamper,
        dataclasses.replace(bundle, input_sha256="c" * 64),
        dataclasses.replace(bundle, result_sha256="c" * 64),
        dataclasses.replace(bundle, calculations=bundle.calculations[:-1]),
        dataclasses.replace(bundle, calculations=bundle.calculations * 2),
    ):
        with pytest.raises(TraceValidationError):
            _validate(candidate, inp, out)
    assert _validate(bundle, inp, out) is not None


# ---- graph battery and registry identity ---------------------------------------

def test_graph_reachability_and_edge_removal(monkeypatch):
    inp = _two_element_input()
    _flip_convergence(monkeypatch, 55.0)  # S2 bin is a non-converged solve
    out = _candidate(inp)
    assert out["fatigue"]["converged"] is False
    bundle = _bundle(inp, out)
    assert len(bundle.calculations) == 5  # 2 spectra x 2 elements + output
    for calculation in bundle.calculations:
        by_id = {step.step_id: step for step in calculation.steps}
        reached, pending = set(), [calculation.final_step_id]
        while pending:
            step_id = pending.pop()
            reached.add(step_id)
            pending.extend(dep.step_id for dep in by_id[step_id].dependencies
                           if dep.step_id not in reached)
        assert reached == set(by_id)
    # Dependency-edge removal fails for every edge of the first element
    # member and the output member. Two fail-closed layers exist: some
    # removals are structurally unconstructible (seal_bundle refuses them),
    # the rest MUST be rejected by the family validator. The construction
    # is deliberately OUTSIDE the pytest.raises block so the validator
    # control is never satisfied vacuously by a construction refusal.
    validator_rejected = 0
    construction_rejected = 0
    targets = (bundle.calculations[0], bundle.calculations[-1])
    for calculation in targets:
        ci = bundle.calculations.index(calculation)
        for si, step in enumerate(calculation.steps):
            for di in range(len(step.dependencies)):
                steps = list(calculation.steps)
                steps[si] = dataclasses.replace(
                    step, dependencies=step.dependencies[:di]
                    + step.dependencies[di + 1:])
                calculations = list(bundle.calculations)
                calculations[ci] = dataclasses.replace(
                    calculation, steps=tuple(steps))
                try:
                    tampered = seal_bundle(dataclasses.replace(
                        bundle, calculations=tuple(calculations)))
                except TraceValidationError:
                    construction_rejected += 1
                    continue
                with pytest.raises(TraceValidationError):
                    _validate(tampered, inp, out)
                validator_rejected += 1
    # Both layers must genuinely fire across the battery.
    assert validator_rejected > 0
    assert construction_rejected > 0


def test_registry_family_and_verdict_identity():
    inp = _mixed_input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    assert REGISTRY_ID == "sector-ct-010-fatigue-v1"
    assert FAMILY_ID == "ct-010-fatigue"
    assert len(bundle.calculations) == 7  # 2 spectra x 3 elements + output
    for calculation in bundle.calculations:
        assert calculation.coverage_id == COVERAGE_ID == "ct-010"
        assert calculation.method_id == METHOD_ID
        final = calculation.steps[-1]
        assert final.quantity_role == ROLE_FINAL
        assert final.result.state == RESULT_FINITE
        # Genuine retained PASS/FAIL decisions with the literal encoding.
        assert final.result.value in STATUS_CODES.values()
        assert "PR-08D.3b" in calculation.assumptions[0]
    payload_json = bundle_to_json(bundle)
    assert "Infinity" not in payload_json and "NaN" not in payload_json


def test_context_partitions_bundles():
    inp = _steel_only_input()
    out = _candidate(inp)
    bundle = _bundle(inp, out)
    other = build_fatigue_trace_family(
        inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
        context={"case": "another case"})
    assert other.to_dict() != bundle.to_dict()
    with pytest.raises(TraceValidationError):
        validate_fatigue_trace_family(
            other, inp, out, input_sha256=INPUT_SHA, result_sha256=RESULT_SHA,
            context=CONTEXT)


def test_retained_app_composition_parity():
    # The retained placement is _run_fatigue_or_invalid: validation first
    # from direct inputs, then the engine; the trace builds from exactly
    # that payload on both branches.
    from app.sector_app import _run_fatigue_or_invalid

    valid = _steel_only_input()
    valid_out = {"fatigue": _run_fatigue_or_invalid(valid)}
    bundle = _bundle(valid, valid_out)
    assert _validate(bundle, valid, valid_out) is not None
    broken = _steel_only_input(fatigue_gamma_s=0.0)
    broken_out = {"fatigue": _run_fatigue_or_invalid(broken)}
    assert broken_out["fatigue"]["valid"] is False
    invalid_bundle = _bundle(broken, broken_out)
    assert invalid_bundle.calculations[0].steps[-1].result.state == (
        RESULT_FAILED)
    assert _validate(invalid_bundle, broken, broken_out) is not None
