"""Application-to-engine fatigue mapping tests, independent of Streamlit."""

from __future__ import annotations

import pathlib
from types import SimpleNamespace
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import fatigue_analysis  # noqa: E402
import fatigue_inputs  # noqa: E402
import load_cases  # noqa: E402
import material_catalog as mat_catalog  # noqa: E402
from sector.materials import Concrete, MildSteel, Prestress  # noqa: E402
from sector.section import Section  # noqa: E402


def _basis(**overrides):
    value = {
        "authority": fatigue_inputs.AUTHORITY_USER,
        "method": fatigue_inputs.METHOD_USER_GROUPED,
        "spectrum_source": "Model M-17, envelope export 4",
        "cycle_count_source": "Traffic study T-03",
        "dynamic_effects": fatigue_inputs.DYNAMIC_INCLUDED,
        "cycle_counting": fatigue_inputs.COUNTING_OTHER,
        "concurrence_basis": "",
        "atypical_traffic": fatigue_inputs.ATYPICAL_NOT_APPLICABLE,
        "approval_reference": "",
        "authority_adjustments": "",
        "notes": "",
    }
    value.update(overrides)
    return value


def _catalogue(*, bond=True):
    catalogue = fatigue_inputs.default_catalog()
    catalogue["items"][0] = fatigue_inputs.apply_preset(
        catalogue["items"][0],
        fatigue_inputs.PRESET_2023_BARS,
    )
    catalogue, tendon_id = fatigue_inputs.add_entry(
        catalogue,
        preset=fatigue_inputs.PRESET_2023_PRETENSION,
    )
    tendon = next(
        item for item in catalogue["items"] if item["id"] == tendon_id
    )
    if bond:
        tendon["bond_ratio_xi"] = 0.7
        tendon["bond_equivalent_diameter_mm"] = 12.5
    catalogue = fatigue_inputs.replace_entry(catalogue, tendon)
    return catalogue, tendon_id


def _base(**overrides):
    catalogue, tendon_detail = _catalogue()
    bars = [(0.0, -0.22, 314.0)]
    tendons = [(0.04, 0.21, 150.0)]
    section = Section.from_polygon(
        corners=[
            (-0.20, -0.30),
            (0.20, -0.30),
            (0.20, 0.30),
            (-0.20, 0.30),
        ],
        bars_xy_area_mm2=bars,
        tendons_xy_area_mm2=tendons,
    )
    mild = MildSteel(
        fytk=550.0,
        fyck=500.0,
        curve=2,
        Es=210_000.0,
    )
    prestress = Prestress(
        curve=7,
        IS=0.005,
        fytk=1640.0,
        futk=1860.0,
        eut=0.035,
        Es=195_000.0,
    )
    mild_catalog = mat_catalog.default_catalog("mild")
    mild_catalog["items"][0].update({
        "fytk": 550.0,
        "fyck": 500.0,
        "Es": 210.0,
    })
    prestress_catalog = mat_catalog.default_catalog("prestress")
    prestress_catalog["items"][0].update({
        "fytk": 1640.0,
        "futk": 1860.0,
        "Es": 195.0,
    })
    value = {
        "fatigue_on": True,
        "fatigue_edition": fatigue_inputs.EC2_2023,
        "fatigue_check_steel": True,
        "fatigue_check_concrete": True,
        "fatigue_gamma_c": 1.595,
        "fatigue_gamma_s": 1.32,
        "fatigue_gamma_ff": 1.10,
        "fatigue_beta_cc_t0": 0.92,
        "fatigue_t0_days": 28.0,
        "fatigue_concrete_k1": 0.85,
        "fatigue_concrete_c": 14.0,
        fatigue_inputs.DETAIL_CATALOG_KEY: catalogue,
        fatigue_inputs.BASIS_KEY: _basis(),
        fatigue_inputs.SPECTRUM_TABLE_KEY:
            fatigue_inputs.normalise_spectrum_table([
                {
                    "spectrum": "Traffic A",
                    "name": "FAT-A1",
                    "description": "High range",
                    "cycles": 2.0e5,
                    "n_long_ed_kn": -800.0,
                    "mx_long_ed_knm": 120.0,
                    "my_long_ed_knm": -15.0,
                    "n_short_ed_kn": 75.0,
                    "mx_short_ed_knm": 80.0,
                    "my_short_ed_knm": 10.0,
                },
                {
                    "spectrum": "Traffic A",
                    "name": "FAT-A2",
                    "cycles": 1.5e6,
                    "n_long_ed_kn": -800.0,
                    "mx_long_ed_knm": 120.0,
                    "n_short_ed_kn": 20.0,
                    "mx_short_ed_knm": 25.0,
                },
                {
                    "spectrum": "Traffic B",
                    "name": "FAT-B1",
                    "cycles": 4.0e5,
                    "n_short_ed_kn": -50.0,
                    "my_short_ed_knm": 30.0,
                },
            ]),
        "section": section,
        "concrete": Concrete(
            fck=40.0,
            gamma_c=1.45,
            alpha_cc=0.95,
        ),
        "bar_elements": [{
            "id": "R1",
            "kind": "bar",
            "x_mm": 0.0,
            "y_mm": -220.0,
            "area_mm2": 314.0,
            "diameter_mm": 20.0,
            "material_id": "M1",
            "fatigue_detail_id": "F1",
        }],
        "tendon_elements": [{
            "id": "P1",
            "kind": "tendon",
            "x_mm": 40.0,
            "y_mm": 210.0,
            "area_mm2": 150.0,
            "diameter_mm": 13.8,
            "material_id": "P1",
            "fatigue_detail_id": tendon_detail,
        }],
        "bar_materials": [mild],
        "tendon_materials": [prestress],
        mat_catalog.MILD_CATALOG_KEY: mild_catalog,
        mat_catalog.PRESTRESS_CATALOG_KEY: prestress_catalog,
        "nl": 18.0,
        "ns": 6.5,
        "void_error": None,
        "steel_error": None,
        "material_error": None,
    }
    value.update(overrides)
    return value


def test_prepare_maps_signs_materials_details_and_full_factors_once():
    prepared = fatigue_analysis.prepare(_base())

    first = prepared.spectra["Traffic A"][0]
    assert first.p_long_kn == 800.0
    assert first.p_short_kn == -75.0
    assert (first.mx_long_knm, first.my_long_knm) == (120.0, -15.0)
    assert (first.mx_short_knm, first.my_short_knm) == (80.0, 10.0)
    assert prepared.solver_element_ids == ("R1", "P1")
    assert prepared.n_mult == pytest.approx([1.05, 0.975])
    assert prepared.prestress_stress == pytest.approx(
        [0.0, 195_000.0 * 0.005 * 1000.0]
    )

    bar, tendon = prepared.reinforcement
    assert (bar.element_id, bar.kind, bar.detail_id) == ("R1", "mild", "F1")
    assert bar.delta_sigma_rsk_mpa == 130.0
    assert bar.fytk_mpa == 550.0
    assert bar.fyck_mpa == 500.0
    assert tendon.bond_ratio_xi == 0.7
    assert tendon.bond_equivalent_diameter_mm == 12.5
    assert prepared.concrete.gamma_c == 1.595
    assert prepared.concrete.alpha_cc == 1.0
    assert prepared.concrete.k1 == 1.0
    assert prepared.gamma_s == 1.32
    assert prepared.gamma_ff == 1.10


def test_bent_bar_reduction_is_resolved_per_element_diameter():
    inp = _base()
    catalogue = inp[fatigue_inputs.DETAIL_CATALOG_KEY]
    bent = fatigue_inputs.apply_preset(
        catalogue["items"][0],
        fatigue_inputs.PRESET_2023_BENT_BARS,
    )
    bent["mandrel_diameter_mm"] = 80.0
    catalogue["items"][0] = bent

    prepared = fatigue_analysis.prepare(inp)

    expected = 130.0 * min(1.0, 0.35 + 0.026 * 80.0 / 20.0)
    assert prepared.reinforcement[0].delta_sigma_rsk_mpa == pytest.approx(
        expected
    )


def test_mixed_section_requires_explicit_tendon_bond_inputs():
    inp = _base()
    catalogue, _tendon_detail = _catalogue(bond=False)
    inp[fatigue_inputs.DETAIL_CATALOG_KEY] = catalogue

    errors = fatigue_analysis.validation_errors(inp)

    assert any("P1: bond_ratio_xi is required" in error for error in errors)
    assert any(
        "P1: bond_equivalent_diameter_mm is required" in error
        for error in errors
    )


def test_concrete_parameters_follow_the_selected_edition():
    current = _base()
    current.pop("fatigue_concrete_k1")
    current["concrete"] = SimpleNamespace(fck=40.0)
    prepared_2023 = fatigue_analysis.prepare(current)

    assert prepared_2023.concrete.alpha_cc == 1.0
    assert prepared_2023.concrete.k1 == 1.0

    old = _base(fatigue_edition=fatigue_inputs.EC2_2005_DKNA)
    old.pop("fatigue_concrete_k1")
    old["concrete"] = SimpleNamespace(fck=40.0)
    errors = fatigue_analysis.validation_errors(old)

    assert "Concrete alpha_cc must be a finite number" in errors
    assert (
        "Concrete fatigue k1 must be a finite number greater than zero"
        in errors
    )
    references = fatigue_analysis.calculation_references(
        fatigue_inputs.EC2_2005_DKNA
    )
    assert "DS/EN 1992-2:2005" in references["concrete"]
    assert "DK NA:2024 explicit input factors" in references["reinforcement"]


def test_standard_detail_presets_must_match_the_selected_fatigue_edition():
    inp = _base()
    catalogue = inp[fatigue_inputs.DETAIL_CATALOG_KEY]
    catalogue["items"][0] = fatigue_inputs.apply_preset(
        catalogue["items"][0],
        fatigue_inputs.PRESET_2005_BARS,
    )

    errors = fatigue_analysis.validation_errors(inp)

    assert any(
        "R1: fatigue detail 'F1' uses DS/EN 1992-1-1:2005 resistance "
        "with DS/EN 1992-1-1:2023" in error
        for error in errors
    )

    old = _base(fatigue_edition=fatigue_inputs.EC2_2005_DKNA)
    old_catalogue = old[fatigue_inputs.DETAIL_CATALOG_KEY]
    old_catalogue["items"] = [
        fatigue_inputs.apply_preset(
            item,
            (
                fatigue_inputs.PRESET_2005_BARS
                if item["kind"] == fatigue_inputs.MILD
                else fatigue_inputs.PRESET_2005_PRETENSION
            ),
        )
        for item in old_catalogue["items"]
    ]
    assert not any(
        "resistance with" in error
        for error in fatigue_analysis.validation_errors(old)
    )


def test_custom_detail_keeps_its_source_and_is_explicit_in_provenance():
    inp = _base()
    catalogue = inp[fatigue_inputs.DETAIL_CATALOG_KEY]
    catalogue["items"][0]["n_star"] = 3.0e6
    catalogue["items"][0]["source"] = "Project S-N test series SN-04"
    inp[fatigue_inputs.DETAIL_CATALOG_KEY] = (
        fatigue_inputs.normalise_catalog(catalogue)
    )

    assert fatigue_analysis.validation_errors(inp) == []
    prepared = fatigue_analysis.prepare(inp)
    detail = prepared.detail_records[0]

    assert detail["preset"] == fatigue_inputs.CUSTOM_PRESET
    assert detail["custom"] is True
    assert detail["edition"] is None
    assert detail["source"] == "Project S-N test series SN-04"
    assert (
        "F1: custom/imported fatigue resistance is used "
        "(source: Project S-N test series SN-04)"
        in fatigue_analysis.validation_warnings(inp)
    )
    result = fatigue_analysis.run_analysis(
        inp,
        engine=lambda *_args, **_kwargs: (
            SimpleNamespace(
                spectrum_name="Traffic A",
                utilisation=0.5,
                converged=True,
                passed=True,
            ),
        ),
    )
    assert result["fatigue_detail_basis"][0]["source"] == (
        "Project S-N test series SN-04"
    )
    assert "custom/imported S-N resistance sources" in (
        result["calculation_references"]["reinforcement"]
    )


def test_builtin_prestress_curve_uses_explicit_catalogue_proof_stress():
    inp = _base()
    inp["tendon_materials"] = [
        Prestress(curve=1, IS=0.005, gamma_y=1.1, Es=195_000.0)
    ]

    assert inp["tendon_materials"][0].fytk == 0.0
    assert fatigue_analysis.validation_errors(inp) == []
    prepared = fatigue_analysis.prepare(inp)
    assert prepared.reinforcement[1].fytk_mpa == 1640.0

    missing = _base()
    missing["tendon_materials"] = [
        Prestress(curve=1, IS=0.005, gamma_y=1.1, Es=195_000.0)
    ]
    missing.pop(mat_catalog.PRESTRESS_CATALOG_KEY)
    assert (
        "P1: characteristic yield/proof stress must be greater than zero"
        in fatigue_analysis.validation_errors(missing)
    )


def test_validation_catches_case_name_collisions_and_element_order_drift():
    inp = _base()
    inp["elastic_cases"] = load_cases.normalise_table(
        [{"name": "fat-a1"}],
        load_cases.ELASTIC_TABLE_KEY,
    )
    inp["bar_elements"][0]["x_mm"] = 10.0

    errors = fatigue_analysis.validation_errors(inp)

    assert any("Case name 'FAT-A1' is duplicated" in error for error in errors)
    assert "R1: x does not match the solver section" in errors


def test_constant_amplitude_authority_methods_reject_multi_bin_groups():
    inp = _base()
    inp[fatigue_inputs.BASIS_KEY] = _basis(
        authority=fatigue_inputs.AUTHORITY_VD,
        method=fatigue_inputs.METHOD_VD_FLM1,
    )

    errors = fatigue_analysis.validation_errors(inp)

    assert any(
        "Traffic A: VD FLM1 - maximum stress range requires one "
        "constant-amplitude bin" == error
        for error in errors
    )


def test_run_passes_exact_prepared_contract_and_returns_compact_summary():
    inp = _base()
    calls = {}

    def fake_engine(section, spectra, nl, ns, **kwargs):
        calls.update(
            section=section,
            spectra=spectra,
            nl=nl,
            ns=ns,
            kwargs=kwargs,
        )
        return (
            SimpleNamespace(
                spectrum_name="Traffic A",
                utilisation=0.72,
                converged=True,
                passed=True,
            ),
            SimpleNamespace(
                spectrum_name="Traffic B",
                utilisation=0.91,
                converged=True,
                passed=True,
            ),
        )

    result = fatigue_analysis.run_analysis(inp, engine=fake_engine)

    assert calls["section"] is inp["section"]
    assert list(calls["spectra"]) == ["Traffic A", "Traffic B"]
    assert (calls["nl"], calls["ns"]) == (18.0, 6.5)
    assert calls["kwargs"]["solver_element_ids"] == ("R1", "P1")
    assert calls["kwargs"]["gamma_s"] == 1.32
    assert calls["kwargs"]["gamma_ff"] == 1.10
    assert np.array_equal(
        calls["kwargs"]["n_mult"],
        np.asarray([1.05, 0.975]),
    )
    assert result["governing_spectrum"] == "Traffic B"
    assert result["utilisation"] == 0.91
    assert result["converged"] is True
    assert result["passed"] is True
    assert result["authority_reference"] == (
        fatigue_inputs.METHOD_REFERENCES[
            fatigue_inputs.METHOD_USER_GROUPED
        ]
    )
    assert "Annex E.5" in result["calculation_references"]["reinforcement"]
    assert "Annex E.7" in result["calculation_references"]["concrete"]


def test_adapter_runs_the_real_engine_for_a_mild_reinforced_section():
    inp = _base(fatigue_check_concrete=False)
    inp["section"] = Section.from_polygon(
        corners=[
            (-0.20, -0.30),
            (0.20, -0.30),
            (0.20, 0.30),
            (-0.20, 0.30),
        ],
        bars_xy_area_mm2=[(0.0, -0.22, 314.0)],
    )
    inp["tendon_elements"] = []
    inp["tendon_materials"] = []
    inp[fatigue_inputs.SPECTRUM_TABLE_KEY] = (
        fatigue_inputs.normalise_spectrum_table([{
            "spectrum": "Commissioning",
            "name": "FAT-C1",
            "cycles": 2.0e5,
            "n_long_ed_kn": -300.0,
            "mx_short_ed_knm": 8.0,
        }])
    )

    result = fatigue_analysis.run_analysis(inp)

    assert len(result["spectra"]) == 1
    assert result["spectra"][0].spectrum_name == "Commissioning"
    assert result["converged"] is True
    assert np.isfinite(result["utilisation"])


def test_concrete_only_check_needs_moduli_but_not_steel_strength_details():
    inp = _base(fatigue_check_steel=False)
    inp["bar_materials"][0] = SimpleNamespace(Es=210_000.0)
    inp["tendon_materials"][0] = SimpleNamespace(
        Es=195_000.0,
        IS=0.005,
    )
    inp["bar_elements"][0]["fatigue_detail_id"] = ""
    inp["tendon_elements"][0]["fatigue_detail_id"] = ""

    assert fatigue_analysis.validation_errors(inp) == []
    prepared = fatigue_analysis.prepare(inp)
    assert prepared.reinforcement == ()
    assert prepared.gamma_s is None


def test_analysis_signature_changes_with_spectrum_basis_and_material_modulus():
    base = _base()
    signature = fatigue_analysis.analysis_signature(base)

    changed_spectrum = _base()
    changed_spectrum[fatigue_inputs.SPECTRUM_TABLE_KEY].loc[
        0, "mx_short_ed_knm"
    ] = 81.0
    changed_basis = _base()
    changed_basis[fatigue_inputs.BASIS_KEY]["notes"] = "Updated audit note"
    changed_material = _base()
    changed_material["bar_materials"][0] = MildSteel(
        fytk=550.0,
        fyck=500.0,
        curve=2,
        Es=205_000.0,
    )
    changed_assignment = _base()
    changed_assignment["bar_elements"][0]["material_id"] = "M2"
    changed_warning = _base()
    changed_warning[fatigue_inputs.DETAIL_CATALOG_KEY]["items"][0][
        "source"
    ] = ""
    changed_source = _base()
    changed_source[fatigue_inputs.DETAIL_CATALOG_KEY]["items"][0][
        "source"
    ] = "Revised source"

    assert fatigue_analysis.analysis_signature(changed_spectrum) != signature
    assert fatigue_analysis.analysis_signature(changed_basis) != signature
    assert fatigue_analysis.analysis_signature(changed_material) != signature
    assert fatigue_analysis.analysis_signature(changed_assignment) != signature
    assert fatigue_analysis.analysis_signature(changed_warning) != signature
    assert fatigue_analysis.analysis_signature(changed_source) != signature
