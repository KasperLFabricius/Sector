"""F-036 reference QA asset and independent-oracle acceptance."""

from __future__ import annotations

import copy
import dataclasses
import io
import pathlib
import re
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
import result_presentation  # noqa: E402
import sector_report  # noqa: E402
from sector import capacity, torsion  # noqa: E402


APP = str(ROOT / "app" / "sector_app.py")
EXPECTED_INPUT_SHA256 = (
    "6d0602b9cdb13ae56b8c5d07ed5a0d5f3c2fe2fa49d037c67114c70a3ab54fdd"
)


def _pub_m01_pdf_text(pdf):
    text = " ".join(
        " ".join((page.extract_text() or "").split())
        for page in PdfReader(io.BytesIO(pdf)).pages
    )
    # The narrow case cell can wrap after the existing hyphen or before E.
    # Join only this exact fixture ID; retain every status, value and other ID.
    return re.sub(r"\bPL-\s*COMPLET\s*E\b", "PL-COMPLETE", text)


@pytest.fixture(scope="module")
def isolated_native_module(tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(
            "SECTOR_AUTOSAVE_DIR",
            str(tmp_path_factory.mktemp("reproducible-module") / "autosave"),
        )
        yield


@pytest.fixture(scope="module")
def calculated_example(isolated_native_module):
    at = AppTest.from_file(APP, default_timeout=180)
    at.session_state["_pending_project"] = reproducible_example.project_json()
    at.run()
    assert not at.exception
    assert not at.error
    at.session_state["_main_page"] = "Analysis"
    at.run()
    at.button(key="calculate").click().run(timeout=300)
    assert not at.exception
    assert [message.value for message in at.error] == [
        "A governing comparison fails or is invalid. Review the "
        "highlighted rows below."
    ]
    assert any(
        message.value == (
            "Interpret each row independently; an aggregate section status is not "
            "calculated."
        )
        for message in at.caption
    )
    assert not at.warning
    return at


def _build_pub_m01_example(*, shear_vy=30.0):
    tables, scalars = project_io.parse_project(reproducible_example.project_json())
    pub_tables = dict(tables)
    bars = tables["bars_base"].copy(deep=True)
    bars.loc[:, "x (mm)"] = [-70.0, 70.0, -70.0, 70.0]
    pub_tables["bars_base"] = bars
    plastic_cases = tables["plastic_cases_base"].copy(deep=True)
    plastic_cases.loc[:, "vy_ed_kn"] = shear_vy
    pub_tables["plastic_cases_base"] = plastic_cases
    pub_scalars = dict(scalars)
    pub_scalars["torsion_tef"] = 60.0
    pub_scalars["strut_cot_min"] = 1.206
    pub_scalars["strut_cot_max"] = 1.206
    pub_scalars[capacity.TORSION_CASE_AUTHORITIES_KEY] = {
        "PL-COMPLETE": {
            capacity.TORSION_CASE_DESIGN_BASIS_KEY: (
                capacity.TORSION_DESIGN_EQUILIBRIUM
            ),
            capacity.TORSION_CASE_MEMBER_SCOPE_KEY: capacity.TORSION_MEMBER_CLOSED,
        }
    }
    at = AppTest.from_file(APP, default_timeout=180)
    at.session_state["_pending_project"] = project_io.dump_project(
        pub_tables,
        pub_scalars,
    )
    at.run()
    assert not at.exception
    assert not at.error
    at.session_state["_main_page"] = "Analysis"
    at.run()
    at.button(key="calculate").click().run(timeout=300)
    assert not at.exception
    return at


@pytest.fixture(scope="module")
def pub_m01_example(isolated_native_module):
    return _build_pub_m01_example()


@pytest.fixture(scope="module")
def pub_m01_required_links_example(isolated_native_module):
    return _build_pub_m01_example(shear_vy=300.0)


def test_reference_download_is_current_schema_complete_and_identity_stable():
    text = reproducible_example.project_json()
    tables, scalars = project_io.parse_project(text)
    assert reproducible_example.PROJECT_NAME == "Sector_v0961_complete_reference.json"
    assert reproducible_example.CHECK_NAME == (
        "Sector_v0961_complete_reference_check.md"
    )
    assert set(tables) == set(project_io.PROJECT_TABLE_KEYS)
    assert reproducible_example.input_sha256() == EXPECTED_INPUT_SHA256
    assert project_io.input_sha256(tables, scalars) == EXPECTED_INPUT_SHA256
    assert scalars["autosave_on"] is True
    assert scalars["capacity_steel_material_id"] == "M1"
    assert scalars["torsion_tef"] == 80.0
    assert (scalars["strut_cot_min"], scalars["strut_cot_max"]) == (1.0, 2.5)
    authority = scalars[capacity.TORSION_CASE_AUTHORITIES_KEY]["PL-COMPLETE"]
    assert authority[capacity.TORSION_CASE_DESIGN_BASIS_KEY] == (
        capacity.TORSION_DESIGN_EQUILIBRIUM
    )
    assert authority[capacity.TORSION_CASE_MEMBER_SCOPE_KEY] == (
        capacity.TORSION_MEMBER_CLOSED
    )
    assert all(scalars[key] for key in (
        "fatigue_on", "minimum_reinforcement_on", "transverse_detailing_on",
        "clear_spacing_on", "shear_on", "torsion_on", "combined_on",
    ))
    assert len(tables["plastic_cases_base"]) == 1
    assert len(tables["elastic_cases_base"]) == 1
    assert len(tables["fatigue_spectrum_base"]) == 2


def test_reference_uniform_wall_respects_every_reinforcement_bound():
    tables, scalars = project_io.parse_project(reproducible_example.project_json())
    outer = [(x / 1000.0, y / 1000.0) for x, y in (
        tables["corners_base"][["x (mm)", "y (mm)"]].itertuples(
            index=False, name=None
        )
    )]
    bars = [(x / 1000.0, y / 1000.0, area) for x, y, area in (
        tables["bars_base"][["x (mm)", "y (mm)", "area (mm2)"]].itertuples(
            index=False, name=None
        )
    )]
    automatic = torsion.tube_properties_with_reinforcement(outer, [], bars)
    assert automatic["valid"] is False
    assert automatic["reason"] == "torsion wall automatic thickness varies by wall"
    assert scalars["torsion_tef"] == 80.0
    declared = torsion.tube_properties_with_reinforcement(
        outer, [], bars, scalars["torsion_tef"]
    )
    assert declared["valid"] is True
    assert declared["tef_user"] is True
    assert declared["tef"] == pytest.approx(80.0)
    assert declared["Ak"] == pytest.approx((0.2 - 0.08) * (0.3 - 0.08))
    assert declared["uk"] == pytest.approx(2.0 * (0.12 + 0.22))
    evidence = declared["wall_evidence"]
    assert evidence["complete"] is True
    assert sorted(wall["lower_bound_mm"] for wall in evidence["walls"]) == (
        pytest.approx([60.0, 60.0, 80.0, 80.0])
    )
    assert all(wall["lower_bound_mm"] <= 80.0 + 1e-10
               for wall in evidence["walls"])


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
    selection = shear["links"]["member_angle_selection"]
    assert selection["objective_count"] == 9
    assert selection["governing_objectives"] == ("shared shear-torsion strut",)
    assert selection["utilisation"] == pytest.approx(expected["member_utilisation"])
    assert expected["neighbor_utilisation"] > expected["member_utilisation"]
    candidates = shear["links"]["chord_candidates"]
    assert len(candidates) == 4
    assert {(item["axis"], item["tension_low"]) for item in candidates} == {
        ("x", True), ("x", False), ("y", True), ("y", False),
    }
    for candidate in candidates:
        assert candidate["valid"] and candidate["conditional"]
        assert candidate["m_rd"] > 0.0 and candidate["z"] > 0.0
        assert candidate["ftd_v"] == 0.0
        # Independent demand arithmetic also closes the full minimax proof: all
        # four genuine conditional faces lie below the transverse lower bound.
        utilisation = (candidate["m_ed"] + candidate["ftd_t"]
                       * candidate["z"] / 2.0) / candidate["m_rd"]
        assert candidate["util"] == pytest.approx(utilisation)
        assert utilisation < expected["member_utilisation"]
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
    action_alone = results["combined"]["action_alone"]
    assert action_alone["v"]["resistance"] == pytest.approx(
        expected["action_alone_vrd_kn"]
    )
    assert action_alone["t"]["resistance"] == pytest.approx(
        expected["action_alone_trd_knm"]
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


def test_pub_m01_provided_links_publish_their_own_pass_in_native_views(
    pub_m01_example,
):
    results = pub_m01_example.session_state.filtered_state["results"]
    inputs = pub_m01_example.session_state.filtered_state[
        "result_input_snapshot"
    ]
    shear = results["shear"]
    provided = capacity.provided_link_shear_assessment(shear)
    public_provided = result_presentation.provided_link_publication_assessment(
        inputs,
        shear,
        torsion_result=results["torsion"],
    )
    link_result = shear["links"]["res"]

    assert provided.valid is True
    assert public_provided.valid is True
    assert provided.resistance == pytest.approx(127.653869995)
    assert provided.utilisation == pytest.approx(0.2350105015)
    assert provided.status == "PASS"
    assert link_result["z"] == pytest.approx(242.58799300907657)
    assert link_result["cot"] == pytest.approx(1.206)
    assert link_result["vrd_s"] == pytest.approx(127.6538699949732)
    assert link_result["vrd_max"] == pytest.approx(271.275663688542)
    nominal = shear["nominal_resistance"]
    assert nominal["route"] == "concrete"
    assert nominal["resistance"] == pytest.approx(47.59286046984239)
    assert nominal["utilisation"] == pytest.approx(30.0 / nominal["resistance"])
    assert nominal["status"] == "PASS"
    detailing = results["transverse_reinforcement"]
    assert detailing["status"] == "FAIL"
    assert detailing["governing"]["kind"] == "torsion_spacing"
    assert detailing["governing"]["provided"] == pytest.approx(150.0)
    assert detailing["governing"]["limit"] == pytest.approx(95.0)
    assert detailing["governing_utilisation"] == pytest.approx(150.0 / 95.0)
    assert shear["links"]["longitudinal_shear_force"] == 0.0
    combined = results["combined"]
    action_alone_shear = combined["action_alone"]["v"]
    assert action_alone_shear["resistance"] == pytest.approx(44.181297943302305)
    assert action_alone_shear["evidence"]["nominal_route"] == "concrete"
    assert combined["r_v"] == pytest.approx(30.0 / 44.181297943302305)
    assert action_alone_shear["resistance"] != pytest.approx(provided.resistance)
    assert combined["transverse"]["shear_fraction"] == 0.0

    pub_m01_example.selectbox(key="view").set_value("Shear").run()
    assert not pub_m01_example.exception
    link_metric = next(
        metric
        for metric in pub_m01_example.metric
        if metric.label == "Provided-link comparison $V_{Ed}/V_{Rd}$"
    )
    assert str(link_metric.value) == "23.5 %"
    assert str(link_metric.delta) == "PASS"
    assert any(
        caption.value
        == "Separate link detailing assessment: "
        + results["transverse_reinforcement"]["status"]
        + ". This detailing result is not a shear-capacity verdict."
        for caption in pub_m01_example.caption
    )

    pub_m01_example.selectbox(key="view").set_value(
        "Results Overview"
    ).run()
    assert not pub_m01_example.exception
    overview = pub_m01_example.table[0].value
    by_check = {row["Check"]: row for _, row in overview.iterrows()}
    assert by_check["Shear without links"]["Status"] == "PASS"
    assert by_check["Shear without links"]["Result"] == "63.0 % (VEd / VRd,c)"
    assert by_check["Shear with links"]["Status"] == "PASS"
    assert by_check["Shear with links"]["Result"] == "23.5 % (non-governing)"
    assert by_check["Shear/torsion link detailing"]["Status"] == "FAIL"


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_pub_m01_report_profiles_publish_provided_link_pass_separately(
    pub_m01_example,
    profile,
):
    state = pub_m01_example.session_state.filtered_state
    pdf = sector_report.build_report(
        {},
        state["result_input_snapshot"],
        state["results"],
        figures=False,
        profile=profile,
    )
    text = _pub_m01_pdf_text(pdf)

    assert "Shear with links PL-COMPLETE PASS 23.5 %" in text
    assert "Shear/torsion link detailing PL-COMPLETE FAIL 157.9 %" in text
    assert text.count("Shear/torsion link detailing PL-COMPLETE") == 1
    assert "Shear/torsion link detailing PL-COMPLETE NOT APPLICABLE" not in text
    if profile != "Brief":
        assert "23.5 % (PASS; non-governing comparison)" in text
        assert "Separate link detailing assessment: FAIL" in text


def test_pub_m01_matching_primary_plastic_fallback_reaches_native_views(
    pub_m01_example,
):
    at = pub_m01_example
    state = at.session_state.filtered_state
    inp = state["result_input_snapshot"]
    baseline = copy.deepcopy(state["results"])
    fallback = copy.deepcopy(baseline)
    selected = fallback["plastic_cases"][0]["results"]
    selected.pop("plastic")
    contexts = result_presentation._worked_case_contexts(inp, fallback, "plastic")
    assert contexts[0][3] is True
    assert contexts[0][2]["plastic"] is fallback["plastic"]
    assert result_presentation.worked_example_selection(inp, fallback) == (
        result_presentation.worked_example_selection(inp, baseline)
    )
    try:
        at.session_state["results"] = fallback
        at.selectbox(key="view").set_value("Shear").run()
        assert not at.exception
        metric = next(
            item for item in at.metric
            if item.label == "Provided-link comparison $V_{Ed}/V_{Rd}$"
        )
        assert str(metric.value) == "23.5 %"
        assert str(metric.delta) == "PASS"
        at.selectbox(key="view").set_value("Results Overview").run()
        assert not at.exception
        overview = next(item.value for item in at.table if "Check" in item.value)
        row = overview.loc[overview["Check"] == "Shear with links"].iloc[0]
        assert row["Status"] == "PASS"
        assert row["Result"] == "23.5 % (non-governing)"
        assert "plastic" not in selected
    finally:
        at.session_state["results"] = baseline
        at.run()


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_pub_m01_matching_primary_plastic_fallback_reaches_actual_reports(
    pub_m01_example, profile, tmp_path,
):
    state = pub_m01_example.session_state.filtered_state
    inp = state["result_input_snapshot"]
    out = copy.deepcopy(state["results"])
    selected = out["plastic_cases"][0]["results"]
    selected.pop("plastic")
    pdf = sector_report.build_report({}, inp, out, figures=False, profile=profile)
    (tmp_path / f"matching-primary-{profile}.pdf").write_bytes(pdf)
    text = _pub_m01_pdf_text(pdf)
    assert "Shear without links PL-COMPLETE PASS 63.0 %" in text
    assert "Shear with links PL-COMPLETE PASS 23.5 %" in text
    if profile != "Brief":
        assert "23.5 % (PASS; non-governing comparison)" in text
    assert "plastic" not in selected


def _pub_m01_unrelated_primary_result(state, operand="Mx_pl"):
    inp = state["result_input_snapshot"]
    out = copy.deepcopy(state["results"])
    out["plastic_cases"][0]["results"].pop("plastic")
    primary = out["plastic"]
    if operand == "P_pl":
        primary["points"][0]["axial_requested"] += 1.0
    elif operand == "missing-axial":
        primary["points"][0].pop("axial_requested")
    elif operand == "missing-applied":
        primary.pop("applied")
    elif operand == "nonfinite-applied":
        primary["applied"] = (float("nan"), primary["applied"][1])
    else:
        applied = list(primary["applied"])
        applied[0 if operand == "Mx_pl" else 1] += 1.0
        primary["applied"] = tuple(applied)
    return inp, out


@pytest.mark.parametrize("operand", (
    "Mx_pl", "My_pl", "P_pl", "missing-axial", "missing-applied",
    "nonfinite-applied",
))
def test_pub_m01_primary_fallback_rejects_unrelated_plastic_actions(
    pub_m01_example, operand,
):
    state = pub_m01_example.session_state.filtered_state
    inp, out = _pub_m01_unrelated_primary_result(state, operand)
    contexts = result_presentation._worked_case_contexts(inp, out, "plastic")
    assert contexts[0][3] is True
    assert "plastic" not in contexts[0][2]
    assert result_presentation.plastic_publication_authority(
        contexts[0][1], contexts[0][2], out,
    ) is None
    selection = result_presentation.worked_example_selection(inp, out)
    assert "plastic" not in selection["families"]
    assert "combined" not in selection["families"]
    rows = result_presentation.multi_case_summary_rows(inp, out)
    combined = [row for row in rows if row["check"].startswith("Combined")]
    assert combined
    assert all(
        row["status"] == "NOT ASSESSED" and row["result"] == "-"
        and row["util"] is None for row in combined
    )
    by_check = {row["check"]: row for row in rows}
    assert by_check["Shear without links"]["status"] == "PASS"
    assert by_check["Shear with links"]["status"] == "PASS"
    assert by_check["Shear with links"]["util"] == pytest.approx(0.2350105015)
    assert "plastic" not in out["plastic_cases"][0]["results"]


def test_pub_m01_unrelated_primary_is_withheld_in_native_views(pub_m01_example):
    at = pub_m01_example
    state = at.session_state.filtered_state
    baseline = copy.deepcopy(state["results"])
    _inp, out = _pub_m01_unrelated_primary_result(state)
    try:
        at.session_state["results"] = out
        at.selectbox(key="view").set_value("Shear").run()
        assert not at.exception
        metric = next(
            item for item in at.metric
            if item.label == "Provided-link comparison $V_{Ed}/V_{Rd}$"
        )
        assert str(metric.value) == "23.5 %"
        assert str(metric.delta) == "PASS"
        at.selectbox(key="view").set_value("M-V-T Combined").run()
        assert not at.exception
        visible = " ".join(
            str(item.value)
            for collection in (at.warning, at.caption, at.markdown)
            for item in collection
        )
        assert "Combined component evidence is not current" in visible
        assert "Recalculate" in visible
        assert not at.metric
        at.selectbox(key="view").set_value("Results Overview").run()
        assert not at.exception
        overview = next(item.value for item in at.table if "Check" in item.value)
        combined = overview.loc[overview["Check"].str.startswith("Combined")]
        assert not combined.empty
        assert set(combined["Status"]) == {"NOT ASSESSED"}
        assert set(combined["Result"]) == {"-"}
        assert "plastic" not in out["plastic_cases"][0]["results"]
    finally:
        at.session_state["results"] = baseline
        at.run()


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_pub_m01_unrelated_primary_is_withheld_in_actual_reports(
    pub_m01_example, profile, tmp_path,
):
    inp, out = _pub_m01_unrelated_primary_result(
        pub_m01_example.session_state.filtered_state,
    )
    pdf = sector_report.build_report({}, inp, out, figures=False, profile=profile)
    (tmp_path / f"unrelated-primary-{profile}.pdf").write_bytes(pdf)
    text = _pub_m01_pdf_text(pdf)
    assert "Combined M-V-T - DK NA sum PL-COMPLETE NOT ASSESSED -" in text
    assert "Shear without links PL-COMPLETE PASS 63.0 %" in text
    assert "Shear with links PL-COMPLETE PASS 23.5 %" in text
    if profile != "Brief":
        assert "Combined component evidence is not current" in text
        assert "23.5 % (PASS; non-governing comparison)" in text
    assert "plastic" not in out["plastic_cases"][0]["results"]


def _pub_m01_shear_payloads(results):
    seen = set()
    candidates = [results]
    candidates.extend(
        entry.get("results") or {}
        for entry in results.get("plastic_cases") or ()
        if isinstance(entry, dict)
    )
    for candidate in candidates:
        shear = candidate.get("shear") if isinstance(candidate, dict) else None
        if isinstance(shear, dict) and id(shear) not in seen:
            seen.add(id(shear))
            yield shear


def _poison_selected_link_child(results, *, require_selected=True):
    for shear in _pub_m01_shear_payloads(results):
        links = shear["links"]
        if require_selected:
            assert shear["nominal_resistance"]["route"] == "links"
        links["shear_geometry"]["duct_factor_links"] = "bad"


def test_pub_m01_native_required_authority_and_incomplete_child_fail_closed(
    pub_m01_example,
):
    baseline = copy.deepcopy(pub_m01_example.session_state["results"])
    old_vrd_c = f"{baseline['shear']['res']['vrd_c']:.3f}"
    old_utilisation = f"{100.0 * baseline['shear']['util']:.1f} %"
    try:
        for shear in _pub_m01_shear_payloads(
            pub_m01_example.session_state["results"]
        ):
            shear["links"].pop("required", None)
        pub_m01_example.selectbox(key="view").set_value("Shear").run()
        assert not pub_m01_example.exception
        assert {metric.label: str(metric.value) for metric in pub_m01_example.metric} == {
            "Applied shear": "-",
            "Resistance $V_{Rd}$": "-",
            "Assessment": "NOT ASSESSED",
        }
        visible = " ".join(
            str(item.value)
            for collection in (
                pub_m01_example.warning,
                pub_m01_example.caption,
                pub_m01_example.markdown,
            )
            for item in collection
        )
        assert "NOT ASSESSED" in visible
        assert old_vrd_c not in visible
        assert old_utilisation not in visible

        pub_m01_example.session_state["results"] = copy.deepcopy(baseline)
        for shear in _pub_m01_shear_payloads(
            pub_m01_example.session_state["results"]
        ):
            del shear["links"]["res"]["vrd_s"]
        pub_m01_example.selectbox(key="view").set_value("Shear").run()
        assert not pub_m01_example.exception
        assert any(
            "provided-link resistance is NOT ASSESSED" in warning.value
            for warning in pub_m01_example.warning
        )
        assert not any(
            metric.label == "Provided-link comparison $V_{Ed}/V_{Rd}$"
            for metric in pub_m01_example.metric
        )
        assert any(
            caption.value == (
                "Separate link detailing assessment: FAIL. "
                "This detailing result is not a shear-capacity verdict."
            )
            for caption in pub_m01_example.caption
        )

        pub_m01_example.selectbox(key="view").set_value(
            "Results Overview"
        ).run()
        assert not pub_m01_example.exception
        overview = pub_m01_example.table[0].value
        by_check = {row["Check"]: row for _, row in overview.iterrows()}
        assert by_check["Shear without links"]["Status"] == "PASS"
        assert by_check["Shear without links"]["Result"] == (
            "63.0 % (VEd / VRd,c)"
        )
        assert by_check["Shear with links"]["Status"] == "NOT ASSESSED"
        assert by_check["Shear with links"]["Result"] == "-"
        assert by_check["Shear/torsion link detailing"]["Status"] == "FAIL"
    finally:
        pub_m01_example.session_state["results"] = baseline
        pub_m01_example.run()


def test_pub_m01_native_hostile_chord_status_fails_closed_without_raw_copy(
    pub_m01_example,
):
    baseline = copy.deepcopy(pub_m01_example.session_state["results"])
    try:
        for shear in _pub_m01_shear_payloads(
            pub_m01_example.session_state["results"]
        ):
            shear["links"]["longitudinal_assessment"]["status"] = []

        pub_m01_example.selectbox(key="view").set_value("Shear").run()

        assert not pub_m01_example.exception
        visible = " ".join(
            str(item.value)
            for collection in (
                pub_m01_example.warning,
                pub_m01_example.caption,
                pub_m01_example.markdown,
            )
            for item in collection
        )
        assert "provided-link resistance is NOT ASSESSED" in visible
        assert "[]" not in visible
        assert any(
            caption.value == (
                "Separate link detailing assessment: FAIL. "
                "This detailing result is not a shear-capacity verdict."
            )
            for caption in pub_m01_example.caption
        )

        pub_m01_example.selectbox(key="view").set_value(
            "Results Overview"
        ).run()
        overview = pub_m01_example.table[0].value
        by_check = {row["Check"]: row for _, row in overview.iterrows()}
        assert "Shear longitudinal chords" not in by_check
        assert by_check["Shear without links"]["Status"] == "PASS"
        assert by_check["Shear without links"]["Result"] == (
            "63.0 % (VEd / VRd,c)"
        )
        assert by_check["Shear with links"]["Status"] == "NOT ASSESSED"
        assert by_check["Shear with links"]["Result"] == "-"
        assert "[]" not in overview.to_string(index=False)
        assert by_check["Shear/torsion link detailing"]["Status"] == "FAIL"
    finally:
        pub_m01_example.session_state["results"] = baseline
        pub_m01_example.run()


def test_pub_m01_native_stale_concrete_input_is_value_free_in_shear_and_overview(
    pub_m01_example,
):
    baseline_results = copy.deepcopy(pub_m01_example.session_state["results"])
    baseline_snapshot = copy.deepcopy(
        pub_m01_example.session_state["result_input_snapshot"]
    )
    baseline_signature = pub_m01_example.session_state["result_sig"]
    stale_snapshot = copy.deepcopy(baseline_snapshot)
    stale_snapshot["concrete"] = dataclasses.replace(
        stale_snapshot["concrete"],
        fck=80.0,
    )
    old_shear = pub_m01_example.session_state["results"]["shear"]
    old_vrd_c = f"{old_shear['res']['vrd_c']:.3f}"
    old_utilisation = f"{100.0 * old_shear['util']:.1f} %"
    try:
        pub_m01_example.session_state["result_input_snapshot"] = stale_snapshot
        pub_m01_example.session_state["result_sig"] = "forced-stale-concrete"
        pub_m01_example.selectbox(key="view").set_value("Shear").run()

        assert not pub_m01_example.exception
        metrics = {metric.label: str(metric.value) for metric in pub_m01_example.metric}
        assert metrics == {
            "Applied shear": "-",
            "Resistance $V_{Rd}$": "-",
            "Assessment": "NOT ASSESSED",
        }
        visible = " ".join(
            str(item.value)
            for collection in (
                pub_m01_example.warning,
                pub_m01_example.caption,
                pub_m01_example.markdown,
            )
            for item in collection
        )
        assert old_vrd_c not in visible
        assert old_utilisation not in visible
        assert not pub_m01_example.get("plotly_chart")
        rendered_tables = " ".join(
            frame.value.to_string(index=False)
            for frame in pub_m01_example.dataframe
        )
        assert old_vrd_c not in rendered_tables
        assert old_utilisation not in rendered_tables

        pub_m01_example.selectbox(key="view").set_value(
            "Results Overview"
        ).run()
        overview = pub_m01_example.table[0].value
        by_check = {row["Check"]: row for _, row in overview.iterrows()}
        assert by_check["Shear without links"]["Status"] == "STALE"
        assert by_check["Shear without links"]["Result"] == "-"
        assert by_check["Shear with links"]["Status"] == "STALE"
        assert by_check["Shear with links"]["Result"] == "-"

        pub_m01_example.session_state["results"] = copy.deepcopy(baseline_results)
        _poison_selected_link_child(
            pub_m01_example.session_state["results"],
            require_selected=False,
        )
        pub_m01_example.selectbox(key="view").set_value("Shear").run()
        assert not pub_m01_example.exception
        assert {metric.label: str(metric.value) for metric in pub_m01_example.metric} == {
            "Applied shear": "-",
            "Resistance $V_{Rd}$": "-",
            "Assessment": "NOT ASSESSED",
        }
        assert not pub_m01_example.get("plotly_chart")
        rendered_tables = " ".join(
            frame.value.to_string(index=False)
            for frame in pub_m01_example.dataframe
        )
        assert old_vrd_c not in rendered_tables
        assert old_utilisation not in rendered_tables
    finally:
        pub_m01_example.session_state["results"] = baseline_results
        pub_m01_example.session_state["result_input_snapshot"] = baseline_snapshot
        pub_m01_example.session_state["result_sig"] = baseline_signature
        pub_m01_example.run()


def test_pub_m01_selected_link_nominal_route_rejects_stale_child_in_native_views(
    pub_m01_required_links_example,
):
    pub_m01_example = pub_m01_required_links_example
    baseline = copy.deepcopy(pub_m01_example.session_state["results"])
    baseline_snapshot = copy.deepcopy(
        pub_m01_example.session_state["result_input_snapshot"]
    )
    baseline_signature = pub_m01_example.session_state["result_sig"]
    try:
        _poison_selected_link_child(
            pub_m01_example.session_state["results"]
        )
        pub_m01_example.selectbox(key="view").set_value("Shear").run()
        assert not pub_m01_example.exception
        assert not any(
            metric.label == "Provided-link comparison $V_{Ed}/V_{Rd}$"
            for metric in pub_m01_example.metric
        )
        assert not any(
            "Nominal utilisation" in metric.label
            or "Utilisation" in metric.label
            for metric in pub_m01_example.metric
        )
        visible = " ".join(
            str(item.value)
            for collection in (
                pub_m01_example.warning,
                pub_m01_example.caption,
                pub_m01_example.markdown,
            )
            for item in collection
        )
        assert "NOT ASSESSED" in visible

        pub_m01_example.selectbox(key="view").set_value(
            "Results Overview"
        ).run()
        overview = pub_m01_example.table[0].value
        by_check = {row["Check"]: row for _, row in overview.iterrows()}
        assert "Shear without links" not in by_check
        assert by_check["Shear with links"]["Status"] == "NOT ASSESSED"
        assert by_check["Shear with links"]["Result"] == "-"
        assert by_check["Shear/torsion link detailing"]["Status"] == "FAIL"
    finally:
        pub_m01_example.session_state["results"] = baseline
        pub_m01_example.session_state["result_input_snapshot"] = baseline_snapshot
        pub_m01_example.session_state["result_sig"] = baseline_signature
        pub_m01_example.run()


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_pub_m01_selected_link_nominal_route_rejects_stale_child_in_reports(
    pub_m01_required_links_example,
    profile,
):
    pub_m01_example = pub_m01_required_links_example
    state = pub_m01_example.session_state.filtered_state
    results = copy.deepcopy(state["results"])
    _poison_selected_link_child(results)
    inp = state["result_input_snapshot"]

    pdf = sector_report.build_report(
        {},
        inp,
        results,
        figures=False,
        profile=profile,
    )
    text = _pub_m01_pdf_text(pdf)

    assert "Shear without links PL-COMPLETE" not in text
    assert "Shear with links PL-COMPLETE NOT ASSESSED -" in text
    assert "Shear/torsion link detailing PL-COMPLETE FAIL 157.9 %" in text
    assert "provided-link resistance evidence is unavailable" not in text
    assert "127.654" not in text


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_pub_m01_stale_concrete_input_suppresses_old_worked_values_in_reports(
    pub_m01_example,
    profile,
):
    state = pub_m01_example.session_state.filtered_state
    inp = copy.deepcopy(state["result_input_snapshot"])
    inp["concrete"] = dataclasses.replace(inp["concrete"], fck=80.0)
    shear = state["results"]["shear"]
    old_vrd_c = f"{shear['res']['vrd_c']:.3f}"
    old_utilisation = f"{100.0 * shear['util']:.1f} %"

    pdf = sector_report.build_report(
        {}, inp, state["results"], figures=False, profile=profile
    )
    text = _pub_m01_pdf_text(pdf)

    assert "Shear without links PL-COMPLETE NOT ASSESSED -" in text
    assert "Shear with links PL-COMPLETE NOT ASSESSED -" in text
    assert old_vrd_c not in text
    assert old_utilisation not in text
    assert "Effective depth d" not in text
    if profile != "Brief":
        assert "Recalculate the shear check before relying on resistance" in text


@pytest.mark.parametrize("profile", ("Standard", "Audit"))
def test_pub_m01_malformed_links_and_stale_concrete_suppress_all_shear_operands(
    pub_m01_example,
    profile,
):
    state = pub_m01_example.session_state.filtered_state
    results = copy.deepcopy(state["results"])
    _poison_selected_link_child(results, require_selected=False)
    inp = copy.deepcopy(state["result_input_snapshot"])
    inp["concrete"] = dataclasses.replace(inp["concrete"], fck=80.0)
    old_vrd_c = f"{state['results']['shear']['res']['vrd_c']:.3f}"

    pdf = sector_report.build_report(
        {}, inp, results, figures=False, profile=profile
    )
    text = _pub_m01_pdf_text(pdf)

    assert "Shear without links PL-COMPLETE NOT ASSESSED -" in text
    assert "Shear with links PL-COMPLETE NOT ASSESSED -" in text
    assert old_vrd_c not in text
    assert "Effective depth d" not in text


@pytest.mark.parametrize("profile", ("Standard", "Audit"))
@pytest.mark.parametrize(
    "attack",
    ("method", "concrete", "diameter", "cotangent"),
)
def test_pub_m01_reports_bind_provided_links_to_current_input(
    pub_m01_example,
    profile,
    attack,
):
    state = pub_m01_example.session_state.filtered_state
    inp = copy.deepcopy(state["result_input_snapshot"])
    if attack == "method":
        inp["shear_method"] = next(
            method
            for method in capacity.SHEAR_METHODS
            if method != inp["shear_method"]
        )
    elif attack == "concrete":
        inp["concrete"] = dataclasses.replace(
            inp["concrete"],
            fck=inp["concrete"].fck + 1.0,
        )
    elif attack == "diameter":
        inp["shear_link_dia"] += 1.0
    else:
        inp["strut_cot_min"] += 0.1

    pdf = sector_report.build_report(
        {},
        inp,
        state["results"],
        figures=False,
        profile=profile,
    )
    text = _pub_m01_pdf_text(pdf)

    concrete_is_current = attack in {"diameter", "cotangent"}
    assert (
        "Shear without links PL-COMPLETE PASS 63.0 %" in text
    ) is concrete_is_current
    if not concrete_is_current:
        assert "Shear without links PL-COMPLETE NOT ASSESSED -" in text
    assert "Shear with links PL-COMPLETE NOT ASSESSED -" in text
    assert "Shear/torsion link detailing PL-COMPLETE FAIL 157.9 %" in text
    assert "23.5 % (PASS; non-governing comparison)" not in text
    assert "Recalculate" in text


@pytest.mark.parametrize(
    "attack",
    (
        "missing-vrd-s",
        "mismatched-minimum",
        "missing-geometry",
        "empty-geometry",
        "malformed-geometry",
        "malformed-member-angle",
        "mismatched-diameter",
        "mismatched-legs",
    ),
)
@pytest.mark.parametrize("profile", ("Standard", "Audit"))
def test_pub_m01_hostile_retained_link_evidence_fails_closed_in_reports(
    pub_m01_example,
    profile,
    attack,
):
    state = pub_m01_example.session_state.filtered_state
    results = copy.deepcopy(state["results"])
    for shear in _pub_m01_shear_payloads(results):
        links = shear["links"]
        if attack == "missing-vrd-s":
            del links["res"]["vrd_s"]
        elif attack == "mismatched-minimum":
            links["res"]["vrd_s"] = 1.0
        elif attack == "missing-geometry":
            del links["shear_geometry"]
        elif attack == "empty-geometry":
            links["shear_geometry"] = {}
        elif attack == "malformed-geometry":
            links["shear_geometry"]["duct_factor_links"] = "bad"
        elif attack == "malformed-member-angle":
            links["member_angle_selection"] = {"objective_labels": True}
        elif attack == "mismatched-diameter":
            links["dia"] *= 2.0
        else:
            links["legs"] *= 2.0

    pdf = sector_report.build_report(
        {},
        state["result_input_snapshot"],
        results,
        figures=False,
        profile=profile,
    )
    text = _pub_m01_pdf_text(pdf)

    assert "Shear with links PL-COMPLETE NOT ASSESSED -" in text
    assert "Shear/torsion link detailing PL-COMPLETE FAIL 157.9 %" in text
    assert text.count("Shear/torsion link detailing PL-COMPLETE") == 1
    assert "Shear/torsion link detailing PL-COMPLETE NOT APPLICABLE" not in text
    assert "23.5 % (PASS; non-governing comparison)" not in text
    assert "provided-link resistance evidence is unavailable" not in text
    assert "Recalculate the reinforced-shear check" in text


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
    assert "Saved-input reference" in pack
    assert "SHA-256" not in pack
    assert "schema" not in pack.casefold()
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
    # Two worked body headings and their two visible contents entries.
    assert text.count("Crack width worked - governing case") == 4
    assert "Independent bridge calculations" not in text
    assert "Calculation trace" not in text
