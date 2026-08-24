"""Application-to-engine fatigue mapping tests, independent of Streamlit."""

from __future__ import annotations

import math
import pathlib
import sys
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import fatigue_analysis  # noqa: E402
import fatigue_inputs  # noqa: E402
import fatigue_presentation  # noqa: E402
import load_cases  # noqa: E402
import material_catalog as mat_catalog  # noqa: E402

from sector import fatigue  # noqa: E402
from sector.design_standards import (  # noqa: E402
    Capability,
    DesignBasisKey,
    capability_binding,
)
from sector.engineer_message import EngineerMessage  # noqa: E402
from sector.materials import Concrete, MildSteel, Prestress  # noqa: E402
from sector.section import Section  # noqa: E402


def _message_codes(values) -> set[str]:
    return {
        value.code
        for value in values
        if isinstance(value, EngineerMessage)
    }


def _basis(**overrides):
    value = {
        "method": fatigue_inputs.METHOD_GROUPED,
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
        "fatigue_edition": DesignBasisKey.PUBLISHED_2023.value,
        "fatigue_check_steel": True,
        "fatigue_check_concrete": True,
        "fatigue_concrete_method": fatigue_analysis.CONCRETE_MINER,
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
    assert bar.simplified_screen_rule is not None
    assert bar.simplified_screen_rule.threshold_mpa == 73.0
    assert bar.simplified_screen_rule.range_basis == "design"
    assert bar.simplified_screen_rule.max_cycles == 1.0e8
    assert tendon.bond_ratio_xi == 0.7
    assert tendon.bond_equivalent_diameter_mm == 12.5
    assert tendon.simplified_screen_rule is not None
    assert tendon.simplified_screen_rule.threshold_mpa == 95.0
    assert prepared.concrete.gamma_c == 1.595
    assert prepared.concrete.alpha_cc == 1.0
    assert prepared.concrete.k1 == 1.0
    assert prepared.gamma_s == 1.32
    assert prepared.gamma_ff == 1.10
    assert prepared.basis_key is DesignBasisKey.PUBLISHED_2023
    assert prepared.solver_edition == fatigue_inputs.EC2_2023
    assert "project adoption required" in prepared.basis_label
    assert "no Danish National Annex" in prepared.basis_disclosure


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
    assert prepared.reinforcement[0].simplified_screen_rule is not None
    assert (
        prepared.reinforcement[0].simplified_screen_rule.threshold_mpa
        == pytest.approx(
            73.0 * min(1.0, 0.35 + 0.026 * 80.0 / 20.0)
        )
    )


def test_custom_clone_of_named_values_stays_on_detailed_miner_path():
    inp = _base()
    catalogue = inp[fatigue_inputs.DETAIL_CATALOG_KEY]
    named = next(item for item in catalogue["items"] if item["id"] == "F1")
    custom = {
        **named,
        "preset": fatigue_inputs.CUSTOM_PRESET,
        "name": "Imported values matching the 2023 bar preset",
        "source": "Project fatigue curve import SN-2023-copy",
    }
    catalogue["items"] = [
        custom if item["id"] == "F1" else item
        for item in catalogue["items"]
    ]
    inp[fatigue_inputs.DETAIL_CATALOG_KEY] = fatigue_inputs.normalise_catalog(
        catalogue
    )

    assert fatigue_analysis.validation_errors(inp) == []
    prepared = fatigue_analysis.prepare(inp)
    detail = next(item for item in prepared.detail_records if item["id"] == "F1")
    named_reference = fatigue_inputs.default_entry(
        preset=fatigue_inputs.PRESET_2023_BARS
    )
    for field in (
        "n_star",
        "k1",
        "k2",
        "delta_sigma_rsk_mpa",
        "stress_model",
        "bend_reduction",
    ):
        assert detail[field] == named_reference[field]
    assert detail["preset"] == fatigue_inputs.CUSTOM_PRESET
    assert detail["custom"] is True

    bar = prepared.reinforcement[0]
    rule = bar.simplified_screen_rule
    assert rule is not None
    assert rule.detail_class == "custom/imported detail"
    assert rule.threshold_mpa is None
    assert rule.range_basis == ""
    assert rule.max_cycles is None
    assert "not assigned" in rule.reason

    state = fatigue.FatigueBinState(
        name="custom fallback",
        description="",
        cycles=1.0e12,
        converged=True,
        bar_stress_long_mpa=(10.0,),
        bar_stress_total_mpa=(60.0,),
        concrete_compression_long_mpa=(),
        concrete_compression_total_mpa=(),
        elastic_result=None,
        bar_stress_fatigue_total_mpa=(60.0,),
        design_action_factor=prepared.gamma_ff,
        bar_stress_design_total_mpa=(65.0,),
        bar_stress_fatigue_design_total_mpa=(65.0,),
    )
    result = fatigue.assess_reinforcement_spectrum(
        (bar,),
        (state,),
        gamma_s=prepared.gamma_s,
        gamma_ff=prepared.gamma_ff,
    )[0]

    assert result.simplified_screen is not None
    assert result.simplified_screen.status == (
        fatigue.SIMPLIFIED_SCREEN_NOT_APPLICABLE
    )
    assert result.simplified_screen.passed is None
    assert result.damage > 1.0
    assert result.governing_criterion == "Miner damage"
    assert result.utilisation == pytest.approx(result.damage)
    assert result.passed is False


def test_mixed_section_requires_explicit_tendon_bond_inputs():
    inp = _base()
    catalogue, _tendon_detail = _catalogue(bond=False)
    inp[fatigue_inputs.DETAIL_CATALOG_KEY] = catalogue

    errors = fatigue_analysis.validation_errors(inp)

    assert "FATIGUE-BOND" in _message_codes(errors)


def test_concrete_parameters_follow_the_selected_edition():
    current = _base()
    current.pop("fatigue_concrete_k1")
    current["concrete"] = SimpleNamespace(fck=40.0)
    prepared_2023 = fatigue_analysis.prepare(current)

    assert prepared_2023.concrete.alpha_cc == 1.0
    assert prepared_2023.concrete.k1 == 1.0

    old = _base(
        fatigue_edition=DesignBasisKey.FIRST_GEN_DK_NA_2024.value
    )
    old.pop("fatigue_concrete_k1")
    old["concrete"] = SimpleNamespace(fck=40.0)
    errors = fatigue_analysis.validation_errors(old)

    assert "FATIGUE-ALPHA-CC" in _message_codes(errors)
    assert "FATIGUE-K1" in _message_codes(errors)
    references = fatigue_analysis.calculation_references(
        DesignBasisKey.FIRST_GEN_DK_NA_2024
    )
    assert "DS/EN 1992-2:2005" in references["concrete"]
    binding = capability_binding(
        DesignBasisKey.FIRST_GEN_DK_NA_2024,
        Capability.REINFORCEMENT_FATIGUE,
    )
    assert "first-generation fatigue equations" in binding.disclosure
    assert "user-supplied factors" in binding.disclosure


@pytest.mark.parametrize(
    "invalid_basis",
    [
        fatigue_inputs.EC2_2005,
        fatigue_inputs.EC2_2005_DKNA,
        fatigue_inputs.EC2_2023,
        DesignBasisKey.PUBLISHED_2023.value + " ",
        "something containing 2023",
    ],
)
def test_fatigue_basis_dispatch_rejects_labels_whitespace_and_substrings(
        invalid_basis):
    inp = _base(fatigue_edition=invalid_basis)

    errors = fatigue_analysis.validation_errors(inp)

    assert "FATIGUE-BASIS" in _message_codes(errors)
    with pytest.raises(ValueError, match="fatigue input validation failed"):
        fatigue_analysis.prepare(inp)
    with pytest.raises(ValueError, match="registered basis keys"):
        fatigue_analysis.calculation_references(invalid_basis)


def test_standard_detail_presets_must_match_the_selected_fatigue_edition():
    inp = _base()
    catalogue = inp[fatigue_inputs.DETAIL_CATALOG_KEY]
    catalogue["items"][0] = fatigue_inputs.apply_preset(
        catalogue["items"][0],
        fatigue_inputs.PRESET_2005_BARS,
    )

    errors = fatigue_analysis.validation_errors(inp)

    assert "FATIGUE-DETAIL-EDITION" in _message_codes(errors)

    old = _base(
        fatigue_edition=DesignBasisKey.FIRST_GEN_DK_NA_2024.value
    )
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
    assert "FATIGUE-DETAIL-EDITION" not in _message_codes(
        fatigue_analysis.validation_errors(old)
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
    assert "FATIGUE-CUSTOM-DETAIL" in _message_codes(
        fatigue_analysis.validation_warnings(inp)
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
    assert "FATIGUE-MATERIAL" in _message_codes(
        fatigue_analysis.validation_errors(missing)
    )


def test_validation_catches_case_name_collisions_and_element_order_drift():
    inp = _base()
    inp["elastic_cases"] = load_cases.normalise_table(
        [{"name": "fat-a1"}],
        load_cases.ELASTIC_TABLE_KEY,
    )
    inp["bar_elements"][0]["x_mm"] = 10.0

    errors = fatigue_analysis.validation_errors(inp)

    assert "FATIGUE-SPECTRUM" in _message_codes(errors)
    assert "FATIGUE-ELEMENT-GEOMETRY" in _message_codes(errors)


def test_grouped_spectrum_method_accepts_multiple_bins():
    inp = _base()
    table = fatigue_inputs.normalise_spectrum_table(
        inp[fatigue_inputs.SPECTRUM_TABLE_KEY]
    )
    inp[fatigue_inputs.SPECTRUM_TABLE_KEY] = (
        fatigue_inputs.normalise_spectrum_table(
            [
                *table.to_dict("records"),
                {**table.iloc[0].to_dict(), "name": "FAT-02"},
            ]
        )
    )

    errors = fatigue_analysis.validation_errors(inp)

    assert not any("requires one" in error for error in errors)


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
                miner_damage=0.72,
                yield_utilisation=0.40,
                governing_domain="reinforcement",
                governing_criterion="Miner damage",
                governing_reinforcement_id="R1",
                governing_concrete_fibre=2,
            ),
            SimpleNamespace(
                spectrum_name="Traffic B",
                utilisation=0.91,
                converged=True,
                passed=True,
                miner_damage=0.10,
                yield_utilisation=0.91,
                governing_domain="concrete",
                governing_criterion="compressive stress",
                governing_reinforcement_id="P1",
                governing_concrete_fibre=7,
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
    assert result["governing_domain"] == "concrete"
    assert result["governing_criterion"] == "compressive stress"
    assert result["governing_reinforcement_id"] == "P1"
    assert result["governing_concrete_fibre"] == 7
    headline = fatigue_presentation.overall_note(result)
    assert "governing: concrete fibre 7 - compressive stress" in headline
    assert "governing: -" not in headline
    assert result["miner_damage"] == pytest.approx(0.72)
    assert result["yield_utilisation"] == pytest.approx(0.91)
    assert result["utilisation"] == 0.91
    assert result["converged"] is True
    assert result["passed"] is True
    assert result["method_reference"] == (
        fatigue_inputs.METHOD_REFERENCES[
            fatigue_inputs.METHOD_GROUPED
        ]
    )
    assert "Annex E.5" in result["calculation_references"]["reinforcement"]
    assert "E.7" in result["calculation_references"]["concrete"]
    assert calls["kwargs"]["fatigue_edition"] == fatigue_inputs.EC2_2023
    assert result["basis_key"] == DesignBasisKey.PUBLISHED_2023.value
    assert result["edition"] == result["basis_label"]
    assert "project adoption required" in result["basis_label"]
    assert "no Danish National Annex" in result["basis_disclosure"]
    assert result["capability_bindings"]["reinforcement"]["capability"] == (
        Capability.REINFORCEMENT_FATIGUE.value
    )
    assert result["capability_bindings"]["concrete"]["capability"] == (
        Capability.CONCRETE_FATIGUE_DAMAGE_SUM.value
    )
    assert result["governing_reinforcement_example"] is None
    assert result["governing_concrete_example"] is None


def test_global_fatigue_examples_are_selected_independently_and_fail_closed():
    def spectrum(
        name,
        *,
        reinforcement_util,
        concrete_util,
        search_upper,
        converged=True,
    ):
        reinforcement = SimpleNamespace(
            element_id=f"R-{name}",
            utilisation=reinforcement_util,
            converged=converged,
            governing_criterion="Miner damage",
            governing_bin=f"RB-{name}",
        )
        concrete = SimpleNamespace(
            fibre_index=1,
            utilisation=concrete_util,
            converged=converged,
            governing_criterion="compressive stress",
            governing_bin=f"CB-{name}",
        )
        search = SimpleNamespace(
            upper_damage=search_upper,
            converged=converged,
        )
        return SimpleNamespace(
            spectrum_name=name,
            bins=(SimpleNamespace(converged=converged),),
            reinforcement=(reinforcement,),
            concrete=(concrete,),
            concrete_search=search,
            concrete_method=fatigue_analysis.CONCRETE_MINER,
            governing_reinforcement_id=reinforcement.element_id,
            governing_concrete_fibre=concrete.fibre_index,
        )

    spectra = (
        spectrum(
            "Steel",
            reinforcement_util=0.92,
            concrete_util=0.45,
            search_upper=0.46,
        ),
        spectrum(
            "Concrete",
            reinforcement_util=0.70,
            concrete_util=0.94,
            search_upper=0.97,
        ),
        spectrum(
            "Invalid",
            reinforcement_util=math.inf,
            concrete_util=math.inf,
            search_upper=math.inf,
            converged=False,
        ),
    )

    reinforcement = fatigue_analysis._global_reinforcement_example(spectra)
    concrete = fatigue_analysis._global_concrete_example(spectra)

    assert reinforcement == {
        "spectrum_name": "Steel",
        "element_id": "R-Steel",
        "utilisation": pytest.approx(0.92),
        "criterion": "Miner damage",
        "bin_name": "RB-Steel",
    }
    assert concrete == {
        "spectrum_name": "Concrete",
        "fibre_index": 1,
        "utilisation": pytest.approx(0.97),
        "criterion": "Miner damage upper bound",
        "bin_name": "CB-Concrete",
        "search_upper_bound_governs": True,
    }


def test_global_fatigue_examples_keep_valid_infinity_and_first_tie():
    def spectrum(name, utilisation, *, search_upper=None):
        reinforcement = SimpleNamespace(
            element_id=f"R-{name}",
            utilisation=utilisation,
            converged=True,
            governing_criterion="yield/proof stress",
            governing_bin=name,
        )
        concrete = SimpleNamespace(
            fibre_index=0,
            utilisation=utilisation,
            converged=True,
            governing_criterion="Equivalent amplitude",
            governing_bin=name,
        )
        search = (
            None
            if search_upper is None else
            SimpleNamespace(upper_damage=search_upper, converged=True)
        )
        return SimpleNamespace(
            spectrum_name=name,
            bins=(SimpleNamespace(converged=True),),
            reinforcement=(reinforcement,),
            concrete=(concrete,),
            concrete_search=search,
            concrete_method=fatigue_analysis.CONCRETE_EQUIVALENT,
            governing_reinforcement_id=reinforcement.element_id,
            governing_concrete_fibre=0,
        )

    first = spectrum("First", math.inf, search_upper=0.8)
    second = spectrum("Second", math.inf, search_upper=math.inf)

    reinforcement = fatigue_analysis._global_reinforcement_example(
        (first, second)
    )
    concrete = fatigue_analysis._global_concrete_example((first, second))

    assert reinforcement is not None
    assert reinforcement["spectrum_name"] == "First"
    assert reinforcement["utilisation"] == math.inf
    assert concrete is not None
    assert concrete["spectrum_name"] == "First"
    assert concrete["utilisation"] == math.inf
    assert concrete["search_upper_bound_governs"] is False


def test_equivalent_concrete_method_is_mapped_and_referenced_explicitly():
    inp = _base(
        fatigue_check_steel=False,
        fatigue_concrete_method=fatigue_analysis.CONCRETE_EQUIVALENT,
    )
    prepared = fatigue_analysis.prepare(inp)

    assert prepared.concrete_method == fatigue_analysis.CONCRETE_EQUIVALENT
    assert (
        prepared.concrete.method
        == fatigue_analysis.CONCRETE_EQUIVALENT
    )
    references = fatigue_analysis.calculation_references(
        inp["fatigue_edition"],
        prepared.concrete_method,
    )
    assert "Formula (E.2)" in references["concrete"]


def test_equivalent_only_aggregate_keeps_miner_damage_unavailable():
    inp = _base(
        fatigue_check_steel=False,
        fatigue_concrete_method=fatigue_analysis.CONCRETE_EQUIVALENT,
    )

    result = fatigue_analysis.run_analysis(
        inp,
        engine=lambda *_args, **_kwargs: (
            SimpleNamespace(
                spectrum_name="Equivalent",
                utilisation=0.82,
                converged=True,
                passed=True,
                miner_damage=None,
                yield_utilisation=None,
                governing_domain="concrete",
                governing_criterion="Equivalent amplitude",
                governing_reinforcement_id=None,
                governing_concrete_fibre=4,
            ),
        ),
    )

    assert result["miner_damage"] is None
    assert "max Miner D" not in fatigue_presentation.overall_note(result)


def test_project_concrete_miner_is_uncited_and_validates_its_c_value():
    inp = _base(
        fatigue_check_steel=False,
        fatigue_concrete_method=fatigue_analysis.CONCRETE_PROJECT_MINER,
    )
    prepared = fatigue_analysis.prepare(inp)
    references = fatigue_analysis.calculation_references(
        prepared.basis_key,
        prepared.concrete_method,
    )
    assert references["concrete"] == (
        "Project-defined concrete Miner S-N relation (uncited)"
    )
    assert "FATIGUE-PROJECT-RELATION" in _message_codes(
        fatigue_analysis.validation_warnings(inp)
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
    assert result["calculation_references"]["concrete"] == (
        "Project-defined concrete Miner S-N relation (uncited)"
    )
    assert "concrete" not in result["capability_bindings"]
    assert "Formula 6.106" not in str(result["capability_bindings"])

    invalid = dict(inp)
    invalid["fatigue_concrete_c"] = -1.0
    assert "FATIGUE-CONCRETE-C" in _message_codes(
        fatigue_analysis.validation_errors(invalid)
    )


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


def test_invalid_result_preserves_missing_assignments_without_running_fatigue():
    inp = _base()
    inp["bar_elements"][0]["fatigue_detail_id"] = ""
    inp["tendon_elements"][0]["fatigue_detail_id"] = ""

    errors = fatigue_analysis.validation_errors(inp)
    payload = fatigue_analysis.invalid_result(inp, errors)

    assert payload["valid"] is False
    assert payload["converged"] is False
    assert payload["passed"] is False
    assert payload["spectra"] == ()
    assert payload["utilisation"] is None
    assert payload["basis_key"] == DesignBasisKey.PUBLISHED_2023.value
    assert payload["edition"] == payload["basis_label"]
    assert payload["solver_edition"] == fatigue_inputs.EC2_2023
    assert payload["capability_bindings"] == {}
    assert _message_codes(payload["errors"]) == {"FATIGUE-DETAIL"}
    assert inp["bar_elements"][0]["fatigue_detail_id"] == ""
    assert inp["tendon_elements"][0]["fatigue_detail_id"] == ""


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
