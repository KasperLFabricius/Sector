"""F-036 reference QA asset and independent-oracle acceptance."""

from __future__ import annotations

import io
import pathlib
import sys

from pypdf import PdfReader
import pytest
from streamlit.testing.v1 import AppTest


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tests"))

import manual  # noqa: E402
import project_io  # noqa: E402
import reproducible_example  # noqa: E402
import reference_example_oracle as oracle  # noqa: E402
import sector_report  # noqa: E402


APP = str(ROOT / "app" / "sector_app.py")
EXPECTED_INPUT_SHA256 = (
    "e3a079a72e0c5fb5d74e94107a1d596e036ad326783401e00715e335b85fdca4"
)


@pytest.fixture(scope="module")
def calculated_example():
    at = AppTest.from_file(APP, default_timeout=180)
    at.session_state["_pending_project"] = reproducible_example.project_json()
    at.run()
    assert not at.exception
    assert not at.error
    at.session_state["_main_page"] = "Analysis"
    at.run()
    at.button(key="calculate").click().run(timeout=300)
    assert not at.exception
    assert not at.error
    assert not at.warning
    return at


def test_reference_download_is_current_schema_complete_and_identity_stable():
    text = reproducible_example.project_json()
    tables, scalars = project_io.parse_project(text)
    assert reproducible_example.PROJECT_NAME == "Sector_v095_complete_reference.json"
    assert reproducible_example.CHECK_NAME == (
        "Sector_v095_complete_reference_check.md"
    )
    assert set(tables) == set(project_io.PROJECT_TABLE_KEYS)
    assert reproducible_example.input_sha256() == EXPECTED_INPUT_SHA256
    assert project_io.input_sha256(tables, scalars) == EXPECTED_INPUT_SHA256
    assert scalars["autosave_on"] is True
    assert scalars["capacity_steel_material_id"] == "M1"
    assert all(scalars[key] for key in (
        "fatigue_on", "minimum_reinforcement_on", "transverse_detailing_on",
        "clear_spacing_on", "shear_on", "torsion_on", "combined_on",
    ))
    assert len(tables["plastic_cases_base"]) == 1
    assert len(tables["elastic_cases_base"]) == 1
    assert len(tables["fatigue_spectrum_base"]) == 2


def test_complete_example_retains_results_without_trace_payloads(
    calculated_example,
):
    state = calculated_example.session_state.filtered_state
    results = state["results"]
    assert state["calculation_record"]["input_sha256"] == EXPECTED_INPUT_SHA256
    assert set(results) == {
        "plastic_cases", "plastic", "shear", "torsion", "combined",
        "minimum_reinforcement", "transverse_reinforcement", "elastic_cases",
        "elastic", "clear_spacing", "fatigue", "material_properties",
        "section_properties", "prestress_initial", "elastic_shared",
        "heightened_crack_control", "worked_example_selection",
    }
    assert "calculation_traces" not in results["plastic_cases"][0]["results"]
    assert "calculation_traces" not in results["elastic_cases"][0]["results"]


def test_plastic_elastic_and_crack_outputs_match_independent_oracles(
    calculated_example,
):
    results = calculated_example.session_state.filtered_state["results"]
    plastic = results["plastic"]
    pure_mx = next(point for point in plastic["points"] if point["V"] == 90.0)
    expected_plastic = oracle.plastic_pure_mx()
    assert pure_mx["compression_depth"] == pytest.approx(
        expected_plastic["compression_depth_m"], rel=5.0e-6
    )
    assert pure_mx["Mx"] == pytest.approx(expected_plastic["mx_knm"], rel=1.0e-6)
    assert pure_mx["concrete_force"] == pytest.approx(
        expected_plastic["concrete_force_kn"], rel=1.0e-5
    )
    assert pure_mx["bar_force"] == pytest.approx(
        expected_plastic["steel_force_kn"], rel=1.0e-5
    )
    demand = (80.0**2 + 10.0**2) ** 0.5
    expected_ray = oracle.applied_ray(
        tuple((point["Mx"], point["My"]) for point in plastic["points"]),
        mx_knm=80.0,
        my_knm=10.0,
    )
    assert plastic["util_demand"] == pytest.approx(demand)
    assert plastic["util_resistance"] == pytest.approx(
        expected_ray["resistance_knm"]
    )
    assert plastic["util"] == pytest.approx(expected_ray["utilisation"])
    assert plastic["util_gov"] == expected_ray["segment"]

    elastic = results["elastic"]
    expected_elastic = oracle.cracked_elastic_and_crack_width()
    assert elastic["props_cr"]["cy"] == pytest.approx(
        expected_elastic["neutral_axis_y_m"], abs=5.0e-13
    )
    assert elastic["props_cr"]["Ix"] == pytest.approx(
        expected_elastic["second_moment_m4"], rel=2.0e-12
    )
    assert elastic["max_conc"] == pytest.approx(
        expected_elastic["concrete_compression_mpa"], rel=5.0e-12
    )
    assert elastic["max_steel"] == pytest.approx(
        expected_elastic["steel_stress_mpa"][0], rel=5.0e-12
    )
    assert elastic["crack_output"] == {
        "long_term": {
            "duration": "long_term",
            "value": None,
            "case": None,
            "governing": None,
            "unit": "mm",
            "calculation_state": "NOT ASSESSED",
            "criterion_mm": 0.20,
            "ratio": None,
            "criterion_source": "User input - Analysis settings - long-term",
            "reason": (
                "The load state has no reinforcement in tension, so no crack "
                "opening is applicable."
            ),
            "comparison_equation": None,
        },
        "short_term": {
            "duration": "short_term",
            "value": pytest.approx(
                expected_elastic["crack_width_mm"], rel=5.0e-12
            ),
            "case": "Short-term (fine)",
            "governing": "R1",
            "unit": "mm",
            "calculation_state": "WITHIN USER-SPECIFIED LIMIT",
            "criterion_mm": 0.20,
            "ratio": pytest.approx(
                expected_elastic["crack_width_mm"] / 0.20,
                rel=5.0e-12,
            ),
            "criterion_source": "User input - Analysis settings - short-term",
            "reason": (
                "The calculated crack width is within the user-specified limit."
            ),
            "comparison_equation": "w_k / w_k,criterion",
        },
    }

    heightened = results["heightened_crack_control"]
    diameter = (4.0 * 500.0 / 3.141592653589793) ** 0.5
    fine_base_ratio = (
        diameter * 2.9 / (4.0 * 200_000.0 * 1.0 * 0.20)
    ) ** 0.5
    coarse_base_ratio = (
        diameter * 2.9 / (4.0 * 200_000.0 * 2.0 * 0.20)
    ) ** 0.5
    assert heightened["formula_identity"] == "Formula 7.100 NA"
    assert heightened["bar_diameter_mm"] == pytest.approx(diameter)
    assert heightened["provided_reinforcement_area_mm2"] == pytest.approx(
        1_000.0
    )
    assert heightened["fine"]["base_reinforcement_ratio"] == pytest.approx(
        fine_base_ratio
    )
    assert heightened["coarse"]["base_reinforcement_ratio"] == pytest.approx(
        coarse_base_ratio
    )
    assert heightened["fine"]["required_reinforcement_area_mm2"] == (
        pytest.approx(2.0**0.5 * fine_base_ratio * 60_000.0)
    )
    assert heightened["coarse"]["required_reinforcement_area_mm2"] == (
        pytest.approx(2.0**0.5 * coarse_base_ratio * 90_000.0)
    )
    assert heightened["governing_crack_system"] == "coarse"
    assert heightened["governing_status"] == (
        "PROVIDED AREA BELOW CALCULATED REQUIREMENT"
    )
    assert [row["element_id"] for row in heightened["contributions"]] == [
        "R1",
        "R2",
    ]
    assert all(
        row["diameter_source"] == "equivalent-area-fallback"
        for row in heightened["contributions"]
    )


def test_member_and_detailing_outputs_match_independent_equations(
    calculated_example,
):
    results = calculated_example.session_state.filtered_state["results"]
    shear = results["shear"]
    expected_ray = oracle.applied_ray(
        tuple((point["Mx"], point["My"]) for point in results["plastic"]["points"]),
        mx_knm=80.0,
        my_knm=10.0,
    )
    expected = oracle.member_checks(
        lever_arm_mm=shear["links"]["res"]["z"],
        bending_utilisation=float(expected_ray["utilisation"]),
    )
    assert shear["res"]["k"] == pytest.approx(expected["k"])
    assert shear["res"]["rho_l"] == pytest.approx(expected["rho_l"])
    assert shear["res"]["vrd_c"] == pytest.approx(expected["vrd_c_kn"])
    assert shear["links"]["res"]["cot"] == pytest.approx(expected["cot_theta"])
    assert shear["links"]["res"]["vrd_s"] == pytest.approx(expected["vrd_s_kn"])
    assert shear["links"]["res"]["vrd_max"] == pytest.approx(expected["vrd_max_kn"])
    assert shear["links"]["util"] == pytest.approx(
        expected["shear_links_utilisation"]
    )

    torsion = results["torsion"]
    assert torsion["trd_s"] == pytest.approx(expected["trd_s_knm"])
    assert torsion["trd_max"] == pytest.approx(expected["trd_max_knm"])
    assert torsion["trd_c"] == pytest.approx(expected["trd_c_knm"])
    assert torsion["util"] == pytest.approx(expected["torsion_utilisation"])
    assert results["combined"]["dkna_sum"] == pytest.approx(
        expected["combined_sum"]
    )

    spacing = results["clear_spacing"]["governing"]
    assert spacing["clear_mm"] == pytest.approx(expected["clear_spacing_mm"])
    assert spacing["required_mm"] == pytest.approx(
        expected["required_spacing_mm"]
    )
    assert spacing["status"] == "PASS"
    transverse = results["transverse_reinforcement"]
    ratio = transverse["checks"][0]
    assert ratio["provided"] == pytest.approx(expected["provided_link_ratio"])
    assert ratio["limit"] == pytest.approx(expected["minimum_link_ratio"])
    assert transverse["governing"]["limit"] == pytest.approx(
        expected["torsion_spacing_limit_mm"]
    )
    assert transverse["governing_utilisation"] == pytest.approx(
        expected["torsion_spacing_utilisation"]
    )
    assert transverse["status"] == "FAIL"
    minimum = results["minimum_reinforcement"]["checks"][0]
    expected_area = oracle.minimum_longitudinal_area(
        bt_mm=minimum["bt_mm"], d_mm=minimum["d_mm"]
    )
    assert minimum["as_min_mm2"] == pytest.approx(expected_area)
    assert results["minimum_reinforcement"]["status"] == "PASS"


def test_fatigue_outputs_match_independent_equations(
    calculated_example,
):
    results = calculated_example.session_state.filtered_state["results"]
    expected_fatigue = oracle.fatigue()
    spectrum = results["fatigue"]["spectra"][0]
    reinforcement = spectrum.reinforcement[0]
    concrete = spectrum.concrete[2]
    assert reinforcement.bins[0].stress_range_mpa == pytest.approx(
        expected_fatigue["steel_high_range_mpa"]
    )
    assert reinforcement.bins[1].stress_range_mpa == pytest.approx(
        expected_fatigue["steel_low_range_mpa"]
    )
    assert reinforcement.damage == pytest.approx(expected_fatigue["steel_damage"])
    assert reinforcement.yield_utilisation == pytest.approx(
        expected_fatigue["steel_yield_utilisation"]
    )
    assert concrete.fcd_fat_mpa == pytest.approx(expected_fatigue["fcd_fat_mpa"])
    assert concrete.damage == pytest.approx(expected_fatigue["concrete_damage"])
    assert concrete.stress_utilisation == pytest.approx(
        expected_fatigue["concrete_stress_utilisation"]
    )
    assert spectrum.concrete_search.converged is False
    assert results["fatigue"]["passed"] is False

def test_checking_pack_remains_a_qa_asset_outside_the_end_user_manual():
    pack = reproducible_example.checking_pack()
    assert EXPECTED_INPUT_SHA256 in pack
    flat_pack = " ".join(pack.split())
    for text in (
        "Plastic capacity and applied ray", "Cracked elastic and crack width",
        "DK NA heightened crack-control minimum",
        "the user-specified long-term and short-term ordinary limits are both "
        "0.20 mm",
        "The separate Formula 7.100 NA permitted-width operand is also 0.20 mm",
        "0.1343977823/0.20=0.6719889115",
        "phi=max(25.23132522,25.23132522)=25.23132522 mm",
        "Fine gives base ratio",
        "As,required/As,provided=1.81457651843",
        "As,required/As,provided=1.92464904175",
        "PROVIDED AREA BELOW CALCULATED REQUIREMENT",
        "coarse governs",
        "Detailing and member resistance", "Fatigue", "Report completeness",
        "explicit equations", "genuine demand/resistance verdicts",
    ):
        assert text in flat_pack
    manual_text = "\n".join(
        block[1] for block in manual.manual_blocks()
        if block[0] in {"h1", "h2", "md"}
    )
    assert "Complete reproducible reference" not in manual_text
    assert "complete reference project" not in manual_text
    assert "independent checking pack" not in manual_text


def test_manual_omits_reference_downloads_and_keeps_normal_controls():
    at = AppTest.from_file(APP, default_timeout=90)
    at.run()
    at.session_state["_input_tab"] = "Project"
    at.run()
    at.button(key="open_manual").click().run()
    assert not at.exception
    elements = list(at._tree)
    download_keys = {
        getattr(element, "key", None)
        for element in elements
        if element.type == "download_button"
    }
    assert {
        "manual_dl_complete_reference_project",
        "manual_dl_complete_reference_check",
    }.isdisjoint(download_keys)
    labels = {getattr(element, "label", None) for element in elements}
    assert "Complete reproducible reference" not in labels
    button_keys = {
        getattr(element, "key", None)
        for element in elements
        if element.type == "button"
    }
    assert {"manual_gen_pdf", "manual_close"} <= button_keys
    selectbox_keys = {
        getattr(element, "key", None)
        for element in elements
        if element.type == "selectbox"
    }
    assert "manual_part" in selectbox_keys


def test_tables_only_report_contains_every_main_calculation_chapter(
    calculated_example,
):
    state = calculated_example.session_state.filtered_state
    pdf = sector_report.build_report(
        {},
        state["result_input_snapshot"],
        state["results"],
        figures=False,
        profile="Audit",
    )
    text = " ".join(
        page.extract_text() or ""
        for page in PdfReader(io.BytesIO(pdf)).pages
    )
    for heading in (
        "Section and materials", "Basis of analysis", "Plastic section capacity",
        "Elastic section response and stresses",
        "Cracking threshold and governing crack width - EL-COMPLETE",
        "User-specified crack-width comparison - critical short-term case",
        "DK heightened crack-control minimum",
        "Grouped fatigue", "Shear resistance", "Torsion (thin-walled tube)",
        "Combined bending + shear + torsion (M-V-T)", "minimum reinforcement",
        "Shear/torsion link detailing", "Reinforcement clear spacing",
    ):
        assert heading in text
    assert text.count("Crack width worked - governing case") == 2
    assert "Independent bridge calculations" not in text
    assert "Calculation trace" not in text
