"""Frozen current-schema and numerical oracle for the PR-09B example."""

from __future__ import annotations

import io
import json
import pathlib
import sys

import pypdf
import pytest
from streamlit.testing.v1 import AppTest


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import project_io  # noqa: E402
import worked_example  # noqa: E402
import manual  # noqa: E402
import sector_report  # noqa: E402
from sector import __version__ as sector_version  # noqa: E402


APP = str(ROOT / "app" / "sector_app.py")
ORACLE_PATH = ROOT / "tests" / "fixtures" / "pr09b_worked_example_oracle.json"


def _oracle() -> dict:
    return json.loads(ORACLE_PATH.read_text(encoding="ascii"))


def _close(actual, expected):
    assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12)


def test_downloadable_example_owns_the_complete_current_project_schema():
    oracle = _oracle()
    text = worked_example.project_json()
    payload = json.loads(text)
    tables, scalars = project_io.parse_project(text)

    assert payload["format"] == project_io.FORMAT
    assert payload["version"] == oracle["project_schema"] == project_io.VERSION
    assert payload["provenance"]["sector_version"] == oracle["sector_version"]
    assert sector_version == oracle["sector_version"]
    assert list(payload["tables"]) == oracle["table_keys"]
    assert list(tables) == oracle["table_keys"] == project_io.PROJECT_TABLE_KEYS
    assert set(scalars) == set(project_io.SCALAR_KEYS)
    assert len(scalars) == oracle["scalar_count"]
    assert payload["provenance"]["input_sha256"] == project_io.input_sha256(
        tables, scalars
    )

    round_trip = project_io.dump_project(
        tables,
        scalars,
        app_version=oracle["sector_version"],
        revision="worked-example-round-trip",
    )
    restored_tables, restored_scalars = project_io.parse_project(round_trip)
    assert project_io.input_sha256(restored_tables, restored_scalars) == (
        payload["provenance"]["input_sha256"]
    )


def test_normal_application_run_matches_the_independent_unrounded_oracle():
    expected = _oracle()["expected"]
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["_pending_project"] = worked_example.project_json()
    at.run()
    at.session_state["_main_page"] = "Analysis"
    at.run()
    at.button(key="calculate").click().run()
    assert not at.exception

    results = at.session_state["results"]
    case = results["plastic_cases"][0]["results"]
    elastic = results["elastic_cases"][0]["results"]["elastic"]

    spacing = results["clear_spacing"]
    spacing_expected = expected["clear_spacing"]
    assert spacing["status"] == spacing_expected["status"]
    governing_spacing = spacing["governing"]
    assert governing_spacing["first_id"] == spacing_expected["first_id"]
    assert governing_spacing["second_id"] == spacing_expected["second_id"]
    _close(governing_spacing["clear_mm"], spacing_expected["clear_mm"])
    _close(governing_spacing["required_mm"], spacing_expected["required_mm"])

    plastic = case["plastic"]
    plastic_expected = expected["plastic"]
    assert plastic["converged"] is plastic_expected["converged"]
    _close(plastic["max_mx"], plastic_expected["max_mx_knm"])
    _close(plastic["max_my"], plastic_expected["max_my_knm"])
    _close(plastic["util"], plastic_expected["utilisation"])

    minimum = case["minimum_reinforcement"]
    minimum_expected = expected["minimum_reinforcement"]
    assert minimum["status"] == minimum_expected["status"]
    assert len(minimum["checks"]) == 1
    minimum_check = minimum["checks"][0]
    _close(minimum_check["as_min_mm2"], minimum_expected["as_required_mm2"])
    _close(
        minimum_check["as_provided_mm2"],
        minimum_expected["as_provided_mm2"],
    )
    _close(minimum_check["utilisation"], minimum_expected["utilisation"])

    transverse = case["transverse_reinforcement"]
    transverse_expected = expected["transverse_reinforcement"]
    assert transverse["status"] == transverse_expected["status"]
    assert transverse["governing"]["kind"] == transverse_expected["governing_kind"]
    _close(
        transverse["governing_utilisation"],
        transverse_expected["governing_utilisation"],
    )

    shear = case["shear"]
    shear_expected = expected["shear"]
    assert shear["status"] == shear_expected["status"]
    assert shear["component"] == shear_expected["component"]
    _close(shear["res"]["vrd_c"], shear_expected["vrd_c_kn"])
    _close(shear["links"]["res"]["vrd_s"], shear_expected["vrd_s_kn"])
    _close(shear["links"]["res"]["vrd_max"], shear_expected["vrd_max_kn"])
    _close(shear["links"]["res"]["vrd"], shear_expected["vrd_kn"])
    _close(shear["links"]["util"], shear_expected["links_utilisation"])
    _close(shear["links"]["res"]["cot"], shear_expected["cot_theta"])

    torsion = case["torsion"]
    torsion_expected = expected["torsion"]
    assert torsion["valid"] is torsion_expected["valid"]
    for actual_key, expected_key in (
        ("trd_c", "trd_c_knm"),
        ("trd_s", "trd_s_knm"),
        ("trd_max", "trd_max_knm"),
        ("trd", "trd_knm"),
        ("util", "utilisation"),
        ("cot", "cot_theta"),
    ):
        _close(torsion[actual_key], torsion_expected[expected_key])

    combined = case["combined"]
    combined_expected = expected["combined"]
    assert combined["valid"] is combined_expected["valid"]
    assert combined["dkna_ok"] is combined_expected["dkna_ok"]
    for key in ("r_m", "r_v", "r_t", "dkna_sum", "governing_cot"):
        _close(combined[key], combined_expected[key])

    elastic_expected = expected["elastic"]
    assert elastic["converged"] is elastic_expected["converged"]
    assert elastic["cracked"] is elastic_expected["cracked"]
    _close(elastic["lambda_cr"], elastic_expected["lambda_cr"])
    _close(elastic["sigma_ct"], elastic_expected["sigma_ct_mpa"])
    _close(
        elastic["max_conc"],
        elastic_expected["max_concrete_compression_mpa"],
    )
    _close(elastic["max_steel"], elastic_expected["max_steel_mpa"])

    crack = elastic["crack"]
    crack_expected = expected["crack"]
    assert crack["element_id"] == crack_expected["element_id"]
    assert crack["edition"] == crack_expected["edition"]
    _close(crack["sr_max"], crack_expected["sr_max_mm"])
    _close(crack["wk"], crack_expected["wk_mm"])

    fatigue = results["fatigue"]
    fatigue_expected = expected["fatigue"]
    assert fatigue["converged"] is fatigue_expected["converged"]
    assert fatigue["passed"] is fatigue_expected["passed"]
    assert fatigue["governing_spectrum"] == fatigue_expected["governing_spectrum"]
    _close(fatigue["utilisation"], fatigue_expected["utilisation"])
    spectrum = fatigue["spectra"][0]
    assert spectrum.governing_reinforcement_id == (
        fatigue_expected["governing_reinforcement_id"]
    )
    reinforcement_bin = spectrum.reinforcement[0].bins[0]
    for actual_key, expected_key in (
        ("stress_long_mpa", "steel_stress_long_mpa"),
        ("stress_total_mpa", "steel_stress_total_mpa"),
        ("stress_range_mpa", "steel_stress_range_mpa"),
        ("delta_sigma_rd_mpa", "steel_delta_sigma_rd_mpa"),
        ("cycles_to_failure", "steel_cycles_to_failure"),
        ("damage", "steel_damage"),
        ("yield_utilisation", "steel_yield_utilisation"),
    ):
        _close(getattr(reinforcement_bin, actual_key), fatigue_expected[expected_key])
    fixed_fibre = next(
        item for item in spectrum.concrete
        if item.x_m == pytest.approx(fatigue_expected["fixed_fibre_x_m"])
        and item.y_m == pytest.approx(fatigue_expected["fixed_fibre_y_m"])
    )
    fixed_bin = fixed_fibre.bins[0]
    _close(
        fixed_bin.compression_long_mpa,
        fatigue_expected["fixed_fibre_long_compression_mpa"],
    )
    _close(
        fixed_bin.compression_total_mpa,
        fatigue_expected["fixed_fibre_total_compression_mpa"],
    )
    _close(
        fixed_fibre.stress_utilisation,
        fatigue_expected["fixed_fibre_stress_utilisation"],
    )
    _close(fixed_fibre.damage, fatigue_expected["fixed_fibre_damage"])
    _close(fixed_fibre.fcd_fat_mpa, fatigue_expected["fcd_fat_mpa"])
    search = spectrum.concrete_search
    assert search is not None and search.converged
    for actual_key, expected_key in (
        ("x_m", "search_x_m"),
        ("y_m", "search_y_m"),
        ("damage", "search_damage"),
        ("upper_damage", "search_upper_damage"),
        ("absolute_gap", "search_absolute_gap"),
    ):
        _close(getattr(search, actual_key), fatigue_expected[expected_key])
    assert search.divisions == fatigue_expected["search_divisions"]
    assert search.boxes_evaluated == fatigue_expected["search_boxes"]
    assert search.points_evaluated == fatigue_expected["search_points"]

    bridge = results["bridge"]["calculations"]
    brittle = bridge["brittle_method_b"]["rows"][0]
    brittle_expected = expected["bridge_brittle"]
    assert brittle["status"] == brittle_expected["status"]
    _close(brittle["as_required_mm2"], brittle_expected["as_required_mm2"])
    _close(brittle["utilisation"], brittle_expected["utilisation"])
    wall = bridge["box_walls"]["rows"][0]
    wall_expected = expected["bridge_box_wall"]
    assert wall["status"] == wall_expected["status"]
    _close(wall["utilisation"], wall_expected["utilisation"])
    bridge_crack = bridge["minimum_crack_reinforcement"]["rows"][0]
    bridge_crack_expected = expected["bridge_minimum_crack"]
    assert bridge_crack["status"] == bridge_crack_expected["status"]
    _close(
        bridge_crack["as_required_mm2"],
        bridge_crack_expected["as_required_mm2"],
    )
    _close(bridge_crack["utilisation"], bridge_crack_expected["utilisation"])

    trace = results["calculation_traces"]
    assert trace["bundles"]
    assert not trace["errors"]
    assert len(trace["input_sha256"]) == 64
    assert len(trace["result_sha256"]) == 64
    assert len(trace["content_sha256"]) == 64

    # Exercise the retained publication path with the exact calculated project;
    # this proves that every advertised result family reaches its report chapter.
    pdf = sector_report.build_report(
        {
            "proj_no": "SECTOR-PR09B",
            "proj_name": "Reproducible worked example",
            "section": "400 x 600 mm reinforced-concrete section",
            "rev": "A",
            "author": "Sector example",
            "comments": "Numerical-method hand pack companion.",
        },
        at.session_state["_latest_inputs"],
        results,
        version=sector_version,
        figures=False,
        qa_appendix=True,
    )
    assert pdf[:4] == b"%PDF"
    report_text = "\n".join(
        page.extract_text() for page in pypdf.PdfReader(io.BytesIO(pdf)).pages
    )
    for heading in (
        "Reinforcement clear spacing",
        "Plastic section capacity - PL-DEMO",
        "Longitudinal minimum reinforcement - PL-DEMO",
        "Shear/torsion link detailing - PL-DEMO",
        "Shear resistance - PL-DEMO",
        "Torsion (thin-walled tube) - PL-DEMO",
        "Combined bending + shear + torsion (M-V-T) - PL-DEMO",
        "Elastic section response and stresses - EL-DEMO",
        "Cracking and crack width - EL-DEMO",
        "Grouped fatigue",
        "Independent bridge calculations",
        "Calculation trace",
        "QA appendix - references and notes",
    ):
        assert heading in report_text


def test_hand_pack_pins_every_method_stop_and_report_family():
    oracle = _oracle()
    text = worked_example.hand_pack_markdown()
    for heading in (
        "Clear spacing",
        "Plastic",
        "Minimum reinforcement",
        "Transverse detailing",
        "Shear Vx",
        "Torsion",
        "Combined M-V-T",
        "Elastic/cracking",
        "Crack width",
        "Grouped fatigue",
        "Bridge Method B",
        "Bridge box wall",
        "Bridge minimum crack steel",
    ):
        assert heading in text
    for evidence in (
        "1e-6*max(1,abs(N))",
        "1e-9*max(1,max(abs(target)))",
        "at most 100 bisections",
        "at most 100 Newton iterations",
        "1501 equally spaced candidates",
        "4 x 4 initial",
        "depth 26",
        "at most 200000 boxes",
        "NOT APPLICABLE",
        "INVALID",
    ):
        assert evidence in text
    for expression in oracle["formulae"].values():
        assert expression in text
    for family, field in (
        ("clear_spacing", "clear_mm"),
        ("clear_spacing", "required_mm"),
        ("plastic", "max_mx_knm"),
        ("plastic", "max_my_knm"),
        ("plastic", "utilisation"),
        ("minimum_reinforcement", "as_required_mm2"),
        ("minimum_reinforcement", "as_provided_mm2"),
        ("minimum_reinforcement", "utilisation"),
        ("transverse_reinforcement", "governing_utilisation"),
        ("shear", "links_utilisation"),
        ("shear", "cot_theta"),
        ("torsion", "trd_c_knm"),
        ("torsion", "trd_s_knm"),
        ("torsion", "trd_max_knm"),
        ("torsion", "utilisation"),
        ("combined", "dkna_sum"),
        ("elastic", "lambda_cr"),
        ("elastic", "sigma_ct_mpa"),
        ("elastic", "max_concrete_compression_mpa"),
        ("elastic", "max_steel_mpa"),
        ("crack", "sr_max_mm"),
        ("crack", "wk_mm"),
        ("fatigue", "utilisation"),
        ("fatigue", "steel_damage"),
        ("fatigue", "search_damage"),
        ("fatigue", "search_upper_damage"),
        ("bridge_brittle", "as_required_mm2"),
        ("bridge_brittle", "utilisation"),
        ("bridge_box_wall", "utilisation"),
        ("bridge_minimum_crack", "as_required_mm2"),
        ("bridge_minimum_crack", "utilisation"),
    ):
        assert str(oracle["expected"][family][field]) in text


def test_manual_appendix_pins_the_actual_numerical_methods_and_states():
    text = "\n".join(
        item
        for block in manual.manual_blocks()
        for item in block
        if isinstance(item, str)
    )
    for evidence in (
        "monotone axial equilibrium in compression depth by bisection",
        "at most 100 iterations",
        "10^{-12}c_{full}",
        "r_N=\\sum F-N",
        "endpoint responses",
        "3\\times3",
        "clips the concrete compression zone, solves a Newton correction",
        "\\|\\mathbf r\\|_{\\infty}\\le10^{-9}S",
        "LONG",
        "RST1",
        "TOTAL",
        "DIF",
        "1501",
        "priority branch-and-bound",
        "4\\times4",
        "200000",
        "NOT ASSESSED",
        "NOT APPLICABLE",
        "INVALID",
    ):
        assert evidence in text
