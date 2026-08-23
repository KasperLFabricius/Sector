"""End-to-end profile publication contracts on the frozen report fixture."""

from __future__ import annotations

import io
import re

import pytest
from pypdf import PdfReader

from tools import report_render_fixture


def _profile_pdf(profile: str) -> bytes:
    return report_render_fixture.build_fixture_pdf(
        figures=False,
        profile=profile,
    )


def _profile_text(profile: str) -> str:
    reader = PdfReader(io.BytesIO(_profile_pdf(profile)))
    return " ".join(
        " ".join((page.extract_text() or "").split()) for page in reader.pages
    )


def _brief_text(inp: dict, out: dict) -> str:
    pdf = report_render_fixture.sector_report.build_report(
        {}, inp, out, figures=False, profile="Brief"
    )
    reader = PdfReader(io.BytesIO(pdf))
    return " ".join(
        " ".join((page.extract_text() or "").split()) for page in reader.pages
    )


def _set_elastic_result_fields(out: dict, **values) -> None:
    """Keep top-level and retained per-case Elastic evidence in sync."""

    out["elastic"].update(values)
    for case in out["elastic_cases"]:
        case["results"]["elastic"].update(values)


def test_brief_frozen_fixture_is_a_compact_auditable_engineering_report():
    reader = PdfReader(io.BytesIO(_profile_pdf("Brief")))
    assert reader.pages
    text = _profile_text("Brief")
    for expected in (
        "Report profile Brief",
        "Results overview",
        "Analysis input summary",
        "Geometry and reinforcement",
        "Assigned materials and key properties",
        "Actions",
        "Analysis settings",
        "Crack-control settings",
        "Shear, torsion and detailing settings",
        "Grouped fatigue settings",
        "Governing results and limitations",
        "Brief contains no worked derivation or result chain",
    ):
        assert expected in text


def test_brief_retains_relevant_input_rows_without_standard_derivations():
    text = _profile_text("Brief")
    for expected in (
        "Outer 1 -100.000 -150.000",
        "Bar R1 0.000 -120.000 500.000",
        "Mild / M1 Bars R1",
        "Concrete rings",
        "PL-QA-1",
        "PL-QA-2",
        "EL-QA-1",
        "EL-QA-2",
        "FAT-QA-H",
        "FAT-QA-M",
        "Neutral-axis sweep start 0",
        "Long-term user limit wk,long 0.200 mm",
        "Short-term user limit wk,short 0.200 mm",
        "Formula 7.100 NA permitted width 0.200 mm",
        "Fine effective tension area Ac,eff 60000.000 mm2",
        "Coarse effective tension area Ac,eff 90000.000 mm2",
        "Mild-steel bond selection Ribbed / high bond (k1 = 0.8)",
        "Mild-steel bond coefficient k1 0.800",
        "Shear method DS/EN 1992-1-1:2005 + DK NA:2024",
        "Closed-link diameter 10.0 mm",
        "Spectrum basis notes QA traffic spectrum REF-FAT-01",
        "n = 2.000",
        "preset = EC2:2005 - straight reinforcing bars",
        "source = DS/EN 1992-1-1:2005, Table 6.3N",
        "stress model = fixed; bend reduction = no",
    ):
        assert expected in text
    assert "Retained strain plane" not in text
    assert "Textbook calculation" not in text


def test_brief_retains_tendon_layout_assignment_and_fixed_curve_properties():
    inp = report_render_fixture._inputs()
    out = report_render_fixture._results(inp)
    entry = report_render_fixture.material_catalog.default_entry(
        "prestress", preset="Curve 1 (built-in)"
    )
    law = report_render_fixture.material_catalog.build_material(
        entry, "prestress"
    )
    inp.update({
        "tendons": [(0.045, -0.05, 78.54)],
        "tendon_elements": [{
            "id": "P1",
            "x_mm": 45.0,
            "y_mm": -50.0,
            "area_mm2": 78.54,
            "diameter_mm": 10.0,
            "size_mode": "Diameter",
            "material_id": "P1",
            "fatigue_detail_id": "",
        }],
        "prestress_material_catalog": {
            "version": 1,
            "next_id": 2,
            "items": [entry],
        },
        "prestress_materials": {"P1": law},
        "prestress": law,
    })
    out["worked_example_selection"] = (
        report_render_fixture.result_presentation.worked_example_selection(
            inp, out
        )
    )

    pdf = report_render_fixture.sector_report.build_report(
        {}, inp, out, figures=False, profile="Brief"
    )
    reader = PdfReader(io.BytesIO(pdf))
    text = " ".join(
        " ".join((page.extract_text() or "").split()) for page in reader.pages
    )

    assert "Tendon P1 45.000 -50.000 78.540 10.000 mm; Diameter P1" in text
    assert "Prestress / P1 Tendons P1" in text
    assert "built-in fixed curve 1" in text
    assert "fp0.1k / fpk = 0.000 / 0.000 MPa" not in text


def test_brief_retains_curve_specific_mild_steel_inputs_and_compression_switch():
    inp = report_render_fixture._inputs()
    entries = inp["mild_material_catalog"]["items"]
    entries[0].update({
        "curve": 1,
        "fytk": 510.0,
        "fyck": 470.0,
        "futk": 620.0,
        "eut": 41.0,
        "gamma_y": 1.10,
        "gamma_u": 1.25,
        "gamma_E": 1.05,
        "Es": 205.0,
        "active_in_compression": True,
    })
    entries[1].update({
        "curve": 3,
        "fytk": 525.0,
        "fyck": 315.0,
        "futk": 645.0,
        "eut": 56.0,
        "gamma_y": 1.12,
        "gamma_u": 1.28,
        "gamma_E": 1.04,
        "k": 0.87,
        "ey0t": 3.25,
        "ey0c": 4.75,
        "Es": 198.0,
        "active_in_compression": False,
    })
    laws = {
        item["id"]: report_render_fixture.material_catalog.build_material(
            item, "mild"
        )
        for item in entries
    }
    inp.update({
        "steel": laws["M1"],
        "mild_materials": laws,
        "bar_materials": [
            laws[row["material_id"]] for row in inp["bar_elements"]
        ],
    })

    text = _brief_text(inp, report_render_fixture._results(inp))
    m1 = text[text.index("Mild / M1"):text.index("Mild / M2")]
    m2 = text[text.index("Mild / M2"):text.index("Actions")]

    for expected in (
        "curve 1",
        "fytk / fyck / futk = 510.000 / 470.000 / 620.000 MPa",
        "\u03b5ut = 41.000 \u2030",
        "\u03b3y / \u03b3u / \u03b3E = 1.100 / 1.250 / 1.050",
        "compression branch active = yes",
    ):
        assert expected in m1
    assert "; k =" not in m1
    assert "\u03b50t / \u03b50c" not in m1

    for expected in (
        "curve 3",
        "fytk / fyck / futk = 525.000 / 315.000 / 645.000 MPa",
        "\u03b5ut = 56.000 \u2030",
        "\u03b3y / \u03b3u / \u03b3E = 1.120 / 1.280 / 1.040",
        "k = 0.870",
        "\u03b50t / \u03b50c = 3.250 / 4.750 \u2030",
        "compression branch active = no",
    ):
        assert expected in m2


def test_brief_retains_only_the_active_concrete_exponent():
    inp = report_render_fixture._inputs()
    inp["concrete"] = report_render_fixture.Concrete(
        fck=42.0,
        gamma_c=1.45,
        curve=2,
        alpha_cc=0.91,
        eps_c2=0.0022,
        eps_cu2=0.0033,
        n=1.73,
    )
    text = _brief_text(inp, report_render_fixture._results(inp))
    concrete = text[text.index("Concrete Concrete rings"):text.index("Mild / M1")]
    assert "curve 2" in concrete
    assert "n = 1.730" in concrete

    inp["concrete"] = report_render_fixture.Concrete(
        fck=42.0,
        gamma_c=1.45,
        curve=1,
        alpha_cc=0.91,
        eps_c2=0.0022,
        eps_cu2=0.0033,
        n=3.21,
    )
    text = _brief_text(inp, report_render_fixture._results(inp))
    concrete = text[text.index("Concrete Concrete rings"):text.index("Mild / M1")]
    assert "curve 1" in concrete
    assert "; n =" not in concrete


def test_brief_retains_curve_specific_prestress_inputs():
    inp = report_render_fixture._inputs()
    entries = []
    for material_id, curve, values in (
        ("P1", 6, {
            "IS": 4.8,
            "fytk": 1575.0,
            "futk": 1815.0,
            "eut": 31.0,
            "gamma_y": 1.08,
            "gamma_u": 1.16,
            "gamma_E": 1.03,
            "Es": 193.0,
        }),
        ("P2", 7, {
            "IS": 6.1,
            "fytk": 1685.0,
            "futk": 1915.0,
            "eut": 39.0,
            "gamma_y": 1.11,
            "gamma_u": 1.21,
            "gamma_E": 1.02,
            "k": 0.86,
            "ey0t": 2.75,
            "Es": 201.0,
        }),
    ):
        entry = report_render_fixture.material_catalog.default_entry(
            "prestress", material_id=material_id
        )
        entry.update({
            "name": f"Prestress curve {curve}",
            "preset": "Custom / imported",
            "curve": curve,
            **values,
        })
        entries.append(entry)
    laws = {
        item["id"]: report_render_fixture.material_catalog.build_material(
            item, "prestress"
        )
        for item in entries
    }
    inp.update({
        "tendons": [(-0.04, 0.0, 90.0), (0.04, 0.0, 95.0)],
        "tendon_elements": [
            {
                "id": material_id,
                "x_mm": x_mm,
                "y_mm": 0.0,
                "area_mm2": area,
                "diameter_mm": 11.0,
                "size_mode": "Area",
                "material_id": material_id,
                "fatigue_detail_id": "",
            }
            for material_id, x_mm, area in (
                ("P1", -40.0, 90.0),
                ("P2", 40.0, 95.0),
            )
        ],
        "prestress_material_catalog": {
            "version": 1,
            "next_id": 3,
            "items": entries,
        },
        "prestress_materials": laws,
        "tendon_materials": [laws["P1"], laws["P2"]],
        "prestress": laws["P1"],
    })

    text = _brief_text(inp, report_render_fixture._results(inp))
    p1 = text[text.index("Prestress / P1"):text.index("Prestress / P2")]
    p2 = text[text.index("Prestress / P2"):text.index("Actions")]
    for expected in (
        "curve 6",
        "fp0.1k / fpk = 1575.000 / 1815.000 MPa",
        "\u03b5p,0 = 4.800 \u2030",
        "\u03b5ut = 31.000 \u2030",
        "\u03b3y / \u03b3u / \u03b3E = 1.080 / 1.160 / 1.030",
    ):
        assert expected in p1
    assert "; k =" not in p1
    assert "\u03b50t" not in p1

    for expected in (
        "curve 7",
        "fp0.1k / fpk = 1685.000 / 1915.000 MPa",
        "\u03b5p,0 = 6.100 \u2030",
        "\u03b5ut = 39.000 \u2030",
        "\u03b3y / \u03b3u / \u03b3E = 1.110 / 1.210 / 1.020",
        "k = 0.860",
        "\u03b50t = 2.750 \u2030",
    ):
        assert expected in p2


def test_brief_uses_retained_interaction_and_bond_inputs():
    inp = report_render_fixture._inputs()
    inp.update({
        "interaction": True,
        "sls_bond": "Plain round (k1 = 1.6)",
        "sls_k1": 1.6,
    })
    text = _brief_text(inp, report_render_fixture._results(inp))
    assert "N-M interaction diagrams yes" in text
    assert "Mild-steel bond selection Plain round (k1 = 1.6)" in text
    assert "Mild-steel bond coefficient k1 1.600" in text


def test_brief_mild_bond_inputs_require_active_ordinary_crack_route():
    inp = report_render_fixture._inputs()
    out = report_render_fixture._results(inp)
    inp.update({
        "sls_cw": False,
        "sls_heightened_on": True,
        "sls_bond": "stale heightened-only bond selection",
        "sls_k1": 9.99,
    })
    out["elastic"]["show_cw"] = False
    for case in out["elastic_cases"]:
        case["results"]["elastic"]["show_cw"] = False

    heightened_only = _brief_text(inp, out)
    assert "Crack-control settings" in heightened_only
    assert "DK heightened crack control" in heightened_only
    assert "Mild-steel bond selection" not in heightened_only
    assert "Mild-steel bond coefficient k1" not in heightened_only
    assert "stale heightened-only bond selection" not in heightened_only

    inp["sls_cw"] = True
    ordinary = _brief_text(inp, out)
    assert (
        "Mild-steel bond selection stale heightened-only bond selection"
        in ordinary
    )
    assert "Mild-steel bond coefficient k1 9.990" in ordinary


def test_brief_retains_fctm_for_minimum_reinforcement_without_crack_checks():
    inp = report_render_fixture._inputs()
    out = report_render_fixture._results(inp)
    inp.update({
        "sls_cw": False,
        "sls_heightened_on": False,
        "sls_fctm": 3.37,
        "minimum_reinforcement_on": True,
    })
    out["elastic"]["show_cw"] = False
    for case in out["elastic_cases"]:
        case["results"]["elastic"]["show_cw"] = False

    text = _brief_text(inp, out)
    assert "Crack-control settings" not in text
    assert "Mean tensile strength fctm 3.370 MPa" in text


def test_brief_retains_2023_link_ductility_without_transverse_detailing():
    inp = report_render_fixture._inputs()
    inp.update({
        "shear_on": True,
        "shear_links": True,
        "shear_method": report_render_fixture.codes.EC2_2023.label,
        "combined_on": False,
        "transverse_detailing_on": False,
        "transverse_ductility_class": "A",
    })
    text_a = _brief_text(inp, report_render_fixture._results(inp))
    assert "Link reinforcement ductility class A" in text_a
    assert "2023 minimum-ratio ductility reduction" not in text_a

    inp["transverse_ductility_class"] = "C"
    text_c = _brief_text(inp, report_render_fixture._results(inp))
    assert "Link reinforcement ductility class C" in text_c
    assert "Link reinforcement ductility class A" not in text_c


def test_brief_retains_active_fatigue_detail_modifiers():
    inp = report_render_fixture._inputs()
    out = report_render_fixture._results(inp)
    straight = dict(out["fatigue"]["fatigue_detail_basis"][0])
    bent = {
        **straight,
        "stress_model": report_render_fixture.fatigue_inputs.EC2_2023_BAR_STRESS,
        "bend_reduction": True,
        "mandrel_diameter_mm": 88.0,
    }
    bonded = {
        **straight,
        "id": "F2",
        "name": "Bonded tendon",
        "kind": report_render_fixture.fatigue_inputs.PRESTRESS,
        "stress_model": report_render_fixture.fatigue_inputs.FIXED_STRESS,
        "bend_reduction": False,
        "mandrel_diameter_mm": 0.0,
        "bond_ratio_xi": 0.72,
        "bond_equivalent_diameter_mm": 15.2,
    }
    out["fatigue"]["fatigue_detail_basis"] = (bent, bonded)
    inp.update({
        "tendons": [(0.045, -0.05, 78.54)],
        "tendon_elements": [{
            "id": "P1",
            "x_mm": 45.0,
            "y_mm": -50.0,
            "area_mm2": 78.54,
            "diameter_mm": 10.0,
            "size_mode": "Diameter",
            "material_id": "",
            "fatigue_detail_id": "F2",
        }],
    })

    text = _brief_text(inp, out)
    for expected in (
        "stress model = ec2_2023_bar_diameter",
        "bend reduction = yes",
        "mandrel diameter = 88.000 mm",
        "Fatigue detail F2 Bonded tendon",
        "stress model = fixed",
        "bend reduction = no",
        "bond ratio xi = 0.720",
        "bond-equivalent diameter = 15.200 mm",
    ):
        assert expected in text


def test_brief_retains_2023_concrete_applicability_and_derived_factor():
    inp = report_render_fixture._inputs()
    inp.update({
        "concrete_preset": "DS/EN 1992-1-1:2023",
        "concrete_eta_cc": 0.912345,
        "concrete_k_tc": 0.85,
        "concrete": report_render_fixture.Concrete(
            fck=50.0,
            gamma_c=1.5,
            curve=2,
            alpha_cc=0.912345 * 0.85,
            n=1.75,
        ),
    })
    text_085 = _brief_text(inp, report_render_fixture._results(inp))
    concrete_085 = text_085[
        text_085.index("Concrete Concrete rings"):text_085.index("Mild / M1")
    ]
    for expected in (
        "DS/EN 1992-1-1:2023",
        "\u03b7cc = 0.912345",
        "ktc = 0.85",
        "\u03b1cc = \u03b7cc ktc = 0.775493",
        "n = 1.750",
    ):
        assert expected in concrete_085

    inp["concrete_k_tc"] = 1.0
    inp["concrete"] = report_render_fixture.Concrete(
        fck=50.0,
        gamma_c=1.5,
        curve=2,
        alpha_cc=0.912345,
        n=1.75,
    )
    text_100 = _brief_text(inp, report_render_fixture._results(inp))
    concrete_100 = text_100[
        text_100.index("Concrete Concrete rings"):text_100.index("Mild / M1")
    ]
    assert "ktc = 1.00" in concrete_100
    assert "\u03b1cc = \u03b7cc ktc = 0.912345" in concrete_100
    assert concrete_100 != concrete_085


def test_brief_invalid_fatigue_falls_back_to_assigned_source_catalog():
    inp = report_render_fixture._inputs()
    detail_f1 = report_render_fixture.fatigue_inputs.default_entry(
        preset=report_render_fixture.fatigue_inputs.PRESET_2023_BENT_BARS
    )
    detail_f2 = report_render_fixture.fatigue_inputs.default_entry(
        detail_id="F2",
        preset=report_render_fixture.fatigue_inputs.PRESET_2023_BARS,
    )
    inp[report_render_fixture.fatigue_inputs.DETAIL_CATALOG_KEY]["items"] = [
        detail_f1,
        detail_f2,
    ]
    inp["bar_elements"][0]["fatigue_detail_id"] = "F2"
    inp["bar_elements"][1]["fatigue_detail_id"] = "F1"
    out = report_render_fixture._results(inp)
    out["fatigue"] = report_render_fixture.fatigue_analysis.invalid_result(
        inp, errors=("deliberate invalid-fatigue fixture",)
    )
    assert not out["fatigue"]["fatigue_detail_basis"]

    text = _brief_text(inp, out)
    for expected in (
        "deliberate invalid-fatigue fixture",
        "Fatigue detail F2",
        "Fatigue detail F1",
        "preset = EC2:2023 - bent reinforcing bars",
        "source = DS/EN 1992-1-1:2023, Table E.1, note a",
        "stress model = ec2_2023_bar_diameter",
        "bend reduction = yes",
        "mandrel diameter = 0.000 mm",
    ):
        assert expected in text
    assert text.index("Fatigue detail F2") < text.index("Fatigue detail F1")

    inp["fatigue_check_steel"] = False
    out["fatigue"] = report_render_fixture.fatigue_analysis.invalid_result(
        inp, errors=("concrete-only invalid fatigue",)
    )
    assert "Fatigue detail F1" not in _brief_text(inp, out)


def test_brief_tendon_bond_ratio_is_2023_source_input_not_derived_xi1():
    inp = report_render_fixture._inputs()
    out = report_render_fixture._results(inp)
    inp.update({
        "tendons": [(0.045, -0.05, 78.54)],
        "tendon_elements": [{
            "id": "P1",
            "x_mm": 45.0,
            "y_mm": -50.0,
            "area_mm2": 78.54,
            "diameter_mm": 10.0,
            "size_mode": "Diameter",
            "material_id": "",
            "fatigue_detail_id": "",
        }],
        "sls_code": (
            report_render_fixture.DesignBasisKey.PUBLISHED_2023.value
        ),
        "sls_tendon_xi": 0.72,
    })
    text_2023 = _brief_text(inp, out)
    assert "Bonded-tendon bond-strength ratio xi 0.720" in text_2023
    assert "Prestressing bond ratio xi1" not in text_2023

    inp["sls_tendon_xi"] = 0.0
    assert (
        "Bonded-tendon bond-strength ratio xi not set"
        in _brief_text(inp, out)
    )

    for first_generation_basis in (
        report_render_fixture.DesignBasisKey.FIRST_GEN_BASE.value,
        report_render_fixture.DesignBasisKey.FIRST_GEN_DK_NA_2024.value,
    ):
        inp["sls_code"] = first_generation_basis
        assert "Bonded-tendon bond-strength ratio" not in _brief_text(inp, out)


def test_brief_elastic_basis_fctm_and_coarse_member_follow_live_routes():
    inp = report_render_fixture._inputs()
    out = report_render_fixture._results(inp)
    inp.update({
        "sls_cw": False,
        "sls_heightened_on": False,
        "sls_code": (
            report_render_fixture.DesignBasisKey.PUBLISHED_2023.value
        ),
        "sls_fctm": 3.41,
        "minimum_reinforcement_on": False,
    })
    _set_elastic_result_fields(out, show_cw=False, crack_member=None)
    elastic_only = _brief_text(inp, out)
    assert "Crack-control settings" not in elastic_only
    assert (
        "Ordinary SLS design basis DS/EN 1992-1-1:2023"
        in elastic_only
    )
    assert "Mean tensile strength fctm 3.410 MPa" in elastic_only

    inp.update({
        "sls_cw": True,
        "sls_code": (
            report_render_fixture.DesignBasisKey.FIRST_GEN_DK_NA_2024.value
        ),
        "sls_member": "Slab",
    })
    _set_elastic_result_fields(out, show_cw=True, crack_member="Slab")
    assert "Member type Slab" in _brief_text(inp, out)

    for inactive_basis in (
        report_render_fixture.DesignBasisKey.FIRST_GEN_BASE.value,
        report_render_fixture.DesignBasisKey.PUBLISHED_2023.value,
    ):
        inp["sls_code"] = inactive_basis
        assert "Member type Slab" not in _brief_text(inp, out)


def test_brief_preserves_explicit_zero_spacing_semantics_and_clear_only_edition():
    inp = report_render_fixture._inputs()
    inp.update({
        "detailing_d_upper": 0.0,
        "shear_vx_transverse_leg_spacing": 0.0,
        "shear_vy_transverse_leg_spacing": 0.0,
    })
    text = _brief_text(inp, report_render_fixture._results(inp))
    assert "Upper aggregate size Dupper 0.0 mm" in text
    assert (
        "Maximum Vx-leg spacing along y gross-web upper-bound screen" in text
    )
    assert (
        "Maximum Vy-leg spacing along x gross-web upper-bound screen" in text
    )

    inp.update({
        "shear_on": False,
        "torsion_on": False,
        "combined_on": False,
        "minimum_reinforcement_on": False,
        "transverse_detailing_on": False,
        "clear_spacing_on": True,
    })
    clear_only = _brief_text(inp, report_render_fixture._results(inp))
    assert "Clear-spacing check section-wide" in clear_only
    assert (
        "Detailing edition DS/EN 1992-1-1:2005 + DK NA:2024"
        in clear_only
    )
    assert "Detailing member type" not in clear_only


def test_brief_resistance_fields_follow_active_shear_and_detailing_routes():
    inp = report_render_fixture._inputs()
    inp.update({
        "combined_on": False,
        "shear_on": False,
        "torsion_on": True,
        "minimum_reinforcement_on": False,
        "transverse_detailing_on": False,
        "clear_spacing_on": False,
    })
    torsion_only = _brief_text(inp, report_render_fixture._results(inp))
    assert "Closed-link diameter" in torsion_only
    assert "Effective Vx / Vy link legs" not in torsion_only
    assert "Maximum Vx-leg spacing" not in torsion_only
    assert "Maximum Vy-leg spacing" not in torsion_only

    inp.update({
        "torsion_on": False,
        "transverse_detailing_on": True,
    })
    transverse_only = _brief_text(inp, report_render_fixture._results(inp))
    assert "Detailing member type Beam" in transverse_only
    assert "Section cut direction" not in transverse_only
    assert "Modelled reinforcement direction" not in transverse_only
    assert "Effective Vx / Vy link legs" not in transverse_only
    assert "Maximum Vx-leg spacing" not in transverse_only


def test_brief_2023_shear_and_ductility_conditions_use_effective_method():
    inp = report_render_fixture._inputs()
    inp.update({
        "shear_on": True,
        "shear_links": True,
        "shear_method": report_render_fixture.codes.EC2_2005_DKNA.label,
        "combined_on": False,
        "combined_method": report_render_fixture.codes.EC2_2005_DKNA.label,
        "shear_dlower": 22.0,
        "shear_gamma_v": 1.234,
        "transverse_detailing_on": True,
        "detailing_edition": report_render_fixture.detailing.EC2_2005_DKNA,
        "transverse_ductility_class": "C",
        "transverse_apply_ductility_reduction": True,
    })
    text_2005 = _brief_text(inp, report_render_fixture._results(inp))
    assert "Shear aggregate Dlower" not in text_2005
    assert "Link reinforcement ductility class" not in text_2005
    assert "2023 minimum-ratio ductility reduction" not in text_2005
    assert "Shear partial factor gammaV" not in text_2005

    inp.update({
        "combined_on": True,
        "combined_method": report_render_fixture.codes.EC2_2023.label,
        "torsion_method": report_render_fixture.codes.EC2_2023.label,
        "transverse_detailing_on": False,
    })
    combined_2023 = _brief_text(inp, report_render_fixture._results(inp))
    assert f"Shear method {report_render_fixture.codes.EC2_2023.label}" in combined_2023
    assert "Shear aggregate Dlower 22.0 mm" in combined_2023
    assert "Shear partial factor " + chr(0x3B3) + "V" not in combined_2023
    assert "Link reinforcement ductility class C" in combined_2023
    assert "2023 minimum-ratio ductility reduction" not in combined_2023

    inp.update({
        "combined_on": False,
        "shear_method": report_render_fixture.codes.EC2_2023.label,
        "shear_links": False,
    })
    no_links_2023 = _brief_text(inp, report_render_fixture._results(inp))
    assert "Shear aggregate Dlower 22.0 mm" in no_links_2023
    assert "Shear partial factor " + chr(0x3B3) + "V 1.234" in no_links_2023

    inp.update({
        "shear_on": False,
        "transverse_detailing_on": True,
        "detailing_edition": report_render_fixture.detailing.EC2_2023,
        "transverse_apply_ductility_reduction": True,
    })
    detailing_2023 = _brief_text(inp, report_render_fixture._results(inp))
    assert "Link reinforcement ductility class C" in detailing_2023
    assert "2023 minimum-ratio ductility reduction yes" in detailing_2023


def test_brief_builtin_prestress_proof_stress_is_fatigue_input_only():
    inp = report_render_fixture._inputs()
    entry = report_render_fixture.material_catalog.default_entry(
        "prestress", preset="Curve 1 (built-in)"
    )
    law = report_render_fixture.material_catalog.build_material(
        entry, "prestress"
    )
    inp.update({
        "tendons": [(0.045, -0.05, 78.54)],
        "tendon_elements": [{
            "id": "P1",
            "x_mm": 45.0,
            "y_mm": -50.0,
            "area_mm2": 78.54,
            "diameter_mm": 10.0,
            "size_mode": "Diameter",
            "material_id": "P1",
            "fatigue_detail_id": "",
        }],
        "prestress_material_catalog": {
            "version": 1,
            "next_id": 2,
            "items": [entry],
        },
        "prestress_materials": {"P1": law},
        "prestress": law,
    })
    out = report_render_fixture._results(inp)
    text = _brief_text(inp, out)
    assert "built-in fixed curve 1" in text
    assert (
        "fatigue proof-stress input fp0.1k = 1640.000 MPa "
        "(fatigue yield/proof check input; not a fixed-curve plastic-law field)"
        in text
    )

    inp["fatigue_check_steel"] = False
    out["fatigue"]["checks"]["reinforcement"] = False
    assert "fatigue proof-stress input" not in _brief_text(inp, out)


def _brief_fatigue_route_text(
    *,
    reinforcement: bool,
    concrete: bool,
    basis_key,
    concrete_method: str,
) -> str:
    inp = report_render_fixture._inputs()
    out = report_render_fixture._results(inp)
    inp.update({
        "fatigue_check_steel": reinforcement,
        "fatigue_check_concrete": concrete,
        "fatigue_edition": basis_key.value,
        "fatigue_concrete_method": concrete_method,
        "fatigue_gamma_ff": 1.111,
        "fatigue_gamma_s": 1.222,
        "fatigue_gamma_c": 1.333,
        "fatigue_t0_days": 41.0,
        "fatigue_beta_cc_t0": 0.94,
        "fatigue_concrete_k1": 0.73,
        "fatigue_concrete_c": 19.0,
    })
    fatigue = out["fatigue"]
    resolved = report_render_fixture.sector_report.get_design_basis(basis_key)
    fatigue.update({
        "basis_key": basis_key.value,
        "edition": resolved.label,
        "solver_edition": (
            report_render_fixture.fatigue_inputs.EC2_2023
            if basis_key
            is report_render_fixture.DesignBasisKey.PUBLISHED_2023
            else report_render_fixture.fatigue_inputs.EC2_2005
        ),
        "checks": {
            "reinforcement": reinforcement,
            "concrete": concrete,
        },
        "concrete_method": concrete_method,
        "partial_factors": {
            "gamma_ff": 1.111,
            "gamma_s": 1.222,
            "gamma_c": 1.333,
        },
        "concrete_parameters": {
            "beta_cc_t0": 0.94,
            "k1": 0.73,
            "c": 19.0,
            "method": concrete_method,
        },
        "t0_days": 41.0,
    })
    return _brief_text(inp, out)


def test_brief_fatigue_rows_omit_inactive_concrete_route_inputs():
    method = report_render_fixture.fatigue_analysis.CONCRETE_PROJECT_MINER
    text = _brief_fatigue_route_text(
        reinforcement=True,
        concrete=False,
        basis_key=report_render_fixture.DesignBasisKey.FIRST_GEN_DK_NA_2024,
        concrete_method=method,
    )
    for expected in (
        "Reinforcement fatigue yes",
        "Concrete fatigue no",
        "Action factor \u03b3Ff 1.111",
        "Reinforcement factor \u03b3s 1.222",
        "Spectrum method Grouped action spectrum",
        "Fatigue detail F1",
    ):
        assert expected in text
    for inactive in (
        "Concrete factor \u03b3c,fat",
        "Concrete fatigue method",
        "Concrete age t0",
        "\u03b2cc(t0)",
        "Concrete fatigue k1",
        "Concrete fatigue C",
    ):
        assert inactive not in text


@pytest.mark.parametrize(
    ("basis_key", "method", "expect_k1", "expect_c"),
    (
        (
            report_render_fixture.DesignBasisKey.FIRST_GEN_DK_NA_2024,
            report_render_fixture.fatigue_analysis.CONCRETE_MINER,
            True,
            True,
        ),
        (
            report_render_fixture.DesignBasisKey.FIRST_GEN_BASE,
            report_render_fixture.fatigue_analysis.CONCRETE_EQUIVALENT,
            True,
            False,
        ),
        (
            report_render_fixture.DesignBasisKey.FIRST_GEN_DK_NA_2024,
            report_render_fixture.fatigue_analysis.CONCRETE_PROJECT_MINER,
            True,
            True,
        ),
        (
            report_render_fixture.DesignBasisKey.PUBLISHED_2023,
            report_render_fixture.fatigue_analysis.CONCRETE_MINER,
            False,
            True,
        ),
        (
            report_render_fixture.DesignBasisKey.PUBLISHED_2023,
            report_render_fixture.fatigue_analysis.CONCRETE_EQUIVALENT,
            False,
            False,
        ),
        (
            report_render_fixture.DesignBasisKey.PUBLISHED_2023,
            report_render_fixture.fatigue_analysis.CONCRETE_PROJECT_MINER,
            False,
            True,
        ),
    ),
)
def test_brief_fatigue_concrete_rows_follow_basis_and_method(
    basis_key,
    method,
    expect_k1,
    expect_c,
):
    text = _brief_fatigue_route_text(
        reinforcement=False,
        concrete=True,
        basis_key=basis_key,
        concrete_method=method,
    )
    for expected in (
        "Reinforcement fatigue no",
        "Concrete fatigue yes",
        "Action factor \u03b3Ff 1.111",
        "Concrete factor \u03b3c,fat 1.333",
        f"Concrete fatigue method {method}",
        "Concrete age t0 41.00 days",
        "\u03b2cc(t0) 0.9400",
        "Spectrum method Grouped action spectrum",
    ):
        assert expected in text
    assert "Reinforcement factor \u03b3s" not in text
    assert "Fatigue detail F1" not in text
    assert ("Concrete fatigue k1 0.730" in text) is expect_k1
    assert ("Concrete fatigue C 19.000" in text) is expect_c


def test_brief_tendon_only_crack_route_omits_stale_mild_bond_inputs():
    inp = report_render_fixture._inputs()
    out = report_render_fixture._results(inp)
    inp.update({
        "bars": [],
        "bar_elements": [],
        "tendons": [(0.045, -0.05, 78.54)],
        "tendon_elements": [{
            "id": "P1",
            "x_mm": 45.0,
            "y_mm": -50.0,
            "area_mm2": 78.54,
            "diameter_mm": 10.0,
            "size_mode": "Diameter",
            "material_id": "",
            "fatigue_detail_id": "",
        }],
        "sls_code": (
            report_render_fixture.DesignBasisKey.PUBLISHED_2023.value
        ),
        "sls_bond": "stale mild-bond selection",
        "sls_k1": 9.99,
        "sls_tendon_xi": 0.72,
    })
    text = _brief_text(inp, out)
    assert "Bonded-tendon bond-strength ratio xi 0.720" in text
    assert "Mild-steel bond selection" not in text
    assert "Mild-steel bond coefficient k1" not in text
    assert "stale mild-bond selection" not in text


def test_brief_has_no_furniture_only_or_nearly_blank_spill_page():
    reader = PdfReader(io.BytesIO(_profile_pdf("Brief")))
    for number, page in enumerate(reader.pages, 1):
        body = []
        for raw_line in (page.extract_text() or "").splitlines():
            line = " ".join(raw_line.split())
            if not line or line.startswith(
                (
                    "Project: QA-REFERENCE",
                    f"Sector {report_render_fixture.__version__}",
                    "Rev:",
                )
            ):
                continue
            if line.startswith("Page ") and " of " in line:
                continue
            body.append(line)
        assert len(" ".join(body)) >= 80, number


def test_standard_and_audit_output_is_unchanged_by_the_brief_input_inventory():
    for profile in ("Standard", "Audit"):
        text = _profile_text(profile)
        assert "Analysis input summary" not in text
        assert "Governing results and limitations" not in text
        assert "Section and materials" in text


def test_every_profile_retains_governing_statuses_and_engineering_values():
    expected = (
        "Plastic bending PL-QA-2 FAIL 125.0 %",
        "Crack width - Long-term EL-QA-1 "
        "EXCEEDS USER-SPECIFIED LIMIT 0.213 mm",
        "Crack width - Short-term EL-QA-1 "
        "EXCEEDS USER-SPECIFIED LIMIT 0.213 mm",
        "Torsion PL-QA-1 FAIL 162.7 %",
        "Combined M-V-T - DK NA sum PL-QA-1 FAIL 266.2 %",
        "Fatigue Road traffic PASS 46.1 %",
    )
    for profile in ("Brief", "Standard", "Audit"):
        # A narrow table column can make PDF extraction separate the hyphen from
        # USER-SPECIFIED even though the rendered label is unchanged.
        text = _profile_text(profile).replace(
            "USER -SPECIFIED", "USER-SPECIFIED"
        )
        for value in expected:
            assert value in text


def test_brief_omits_non_governing_requested_results_and_statuses():
    expected = (
        "Non-governing requested results",
        "Plastic bending PL-QA-1 PASS 80.0 %",
        "Crack width - Long-term EL-QA-2 NOT REQUESTED",
        "Crack width - Short-term EL-QA-2 NOT REQUESTED",
    )
    brief = _profile_text("Brief")
    assert all(value not in brief for value in expected)
    for profile in ("Standard", "Audit"):
        text = _profile_text(profile)
        for value in expected:
            assert value in text


def test_brief_omits_non_governing_fatigue_spectra_but_deeper_profiles_retain_them():
    inp = report_render_fixture._inputs()
    inp[report_render_fixture.fatigue_inputs.SPECTRUM_TABLE_KEY][1][
        "spectrum"
    ] = "Rail traffic"
    out = report_render_fixture._results(inp)
    out["fatigue"] = report_render_fixture.fatigue_analysis.run_analysis(inp)

    texts = {}
    for profile in ("Brief", "Standard", "Audit"):
        pdf = report_render_fixture.sector_report.build_report(
            {}, inp, out, figures=False, profile=profile
        )
        reader = PdfReader(io.BytesIO(pdf))
        text = " ".join(
            " ".join((page.extract_text() or "").split())
            for page in reader.pages
        )
        texts[profile] = text
        assert "Fatigue Road traffic PASS 46.1 %" in text
    assert "Fatigue Rail traffic PASS 23.0 %" not in texts["Brief"]
    assert "Fatigue Rail traffic PASS 23.0 %" in texts["Standard"]
    assert "Fatigue Rail traffic PASS 23.0 %" in texts["Audit"]


def test_every_profile_begins_with_the_same_freshness_and_basis_dashboard():
    expected = (
        "Calculation state CURRENT - frozen QA fixture",
        f"Input SHA-256 {'f' * 64}",
        "Selected basis / methods",
        "Report profile",
        "DK heightened crack-control applicability is user-selected",
    )
    for profile in ("Brief", "Standard", "Audit"):
        reader = PdfReader(io.BytesIO(_profile_pdf(profile)))
        cover = " ".join((reader.pages[0].extract_text() or "").split())
        for value in expected:
            assert value in cover


def test_internal_equation_keys_are_audit_only_and_standard_is_default_depth():
    brief = _profile_text("Brief")
    standard = _profile_text("Standard")
    audit = _profile_text("Audit")
    assert "EQ-" not in brief
    assert "EQ-" not in standard
    assert "EQ-MATERIALS.CONCRETE.FCD" in audit
    assert "Report profile Standard" in standard
    assert "Report profile Audit" in audit
    assert "Audit does not mean approved, compliant or certified" in audit


def test_profile_depth_is_monotonic_without_changing_figures_policy():
    pages = {
        profile: len(PdfReader(io.BytesIO(_profile_pdf(profile))).pages)
        for profile in ("Brief", "Standard", "Audit")
    }
    assert pages["Brief"] < pages["Standard"] <= pages["Audit"]


def test_long_case_inventory_uses_a_complete_compact_running_header():
    reader = PdfReader(io.BytesIO(_profile_pdf("Standard")))
    header_fragments = []

    def collect(text, cm, tm, _font, size):
        value = " ".join(text.split())
        y = float(cm[5]) + float(tm[5])
        if value and y > 790 and float(size) == 7.5:
            header_fragments.append(value)

    reader.pages[0].extract_text(visitor_text=collect)
    header = " ".join(header_fragments)
    assert "Cases: Plastic 2; Elastic 2; Fatigue 1" in header
    assert "..." not in header


def test_calculation_subheadings_retain_first_table_or_equation_on_same_page():
    headings = (
        "Concrete",
        "Resistance",
        "Resistances",
        "Retained strain plane",
        "Physical resistance components",
        "Section resultants at convergence",
        "Governing reinforcement and tendon response",
        "Governing cracking threshold",
        "Step 2 - neutralise the long-term concrete stress",
        "Governing reinforcement element - R1",
        "Textbook calculation - governing reinforcement fatigue",
        "Textbook calculation - governing concrete fatigue",
    )
    for profile in ("Standard", "Audit"):
        reader = PdfReader(io.BytesIO(_profile_pdf(profile)))
        seen = set()
        for page in reader.pages:
            fragments = []

            def collect(text, cm, tm, _font, size):
                value = " ".join(text.split())
                if value:
                    fragments.append((
                        value,
                        float(size),
                        float(cm[5]) + float(tm[5]),
                    ))

            page.extract_text(visitor_text=collect)
            for heading in headings:
                matches = [
                    y for value, size, y in fragments
                    if (
                        value == heading
                        or re.fullmatch(rf"\d+\.\d+ {re.escape(heading)}", value)
                    )
                    and size == 11.5
                ]
                for heading_y in matches:
                    seen.add(heading)
                    assert any(
                        y < heading_y - 4
                        and (
                            value.startswith("SECTOR-MATH[")
                            or value.startswith("Table ")
                        )
                        for value, _size, y in fragments
                    ), (profile, heading)
        assert set(headings) <= seen
