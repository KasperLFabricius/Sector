"""Scoped regressions for the independent PUB-M01 R1-R5 review."""
from __future__ import annotations

import copy
import io
import pickle
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pypdf import PdfReader
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "tests")]

import case_analysis
import project_io
import result_presentation as presentation
import sector_report
from test_capacity import _torsion_input, _torsion_wall_bars
from test_torsion import (
    _calculate,
    _fresh,
    _select_view,
    _set,
    _set_and_click,
)

from sector import capacity

pytestmark = pytest.mark.xdist_group("publication_review")


@pytest.fixture(scope="module")
def torsion_root():
    """Use actual capacity kernels; this fixture is not a native calculation."""
    inp = _torsion_input(
        shear_on=False, torsion_on=True, shear_links=True,
        P_pl=0.0, Mx_pl=0.0, torsion_T=100.0,
        bars=_torsion_wall_bars(total_area=5000.0),
    )
    current = presentation._current_torsion_only_children(inp)
    assert current is not None
    root = copy.deepcopy(current["torsion_root"])
    root.update(
        primary=copy.deepcopy(current["torsion_primary"]), subtubes=None,
        member_angle_selection=copy.deepcopy(current["member_angle_selection"]),
        theta_mode=current["theta_mode"], interaction=current["interaction"],
        min_reinf=copy.deepcopy(current["minimum_reinforcement"]),
        applicability=capacity.torsion_applicability(inp, inp["torsion_T"]),
        method=inp["torsion_method"], applicability_blocked=False,
        resistance_status="FAIL",
    )
    root["longitudinal_assessment"] = capacity.torsion_longitudinal_assessment(
        inp, (root["asl_req"],), resistance_assessed=root["valid"],
    )
    root["assessment_status"] = presentation.torsion_assessment_status(root)
    assert root["util"] == pytest.approx(1.2688689959712625)
    assert presentation.torsion_publication_evidence_is_current(inp, None, root) == (True, None)
    return inp, root


@pytest.mark.parametrize("status", (
    "PASS", None, [], "missing", np.array(["PASS", "FAIL"]), np.array("FAIL"),
))
def test_review_r1_rejects_contradictory_torsion_resistance_status(torsion_root, status):
    inp, root = torsion_root
    positive = presentation.result_summary_rows(inp, {"torsion": root})
    current = next(row for row in positive if row["overview_key"] == "torsion:resistance")
    assert current["status"] == "FAIL" and current["result"] == "126.9 %"
    changed = copy.deepcopy(root)
    if type(status) is str and status == "missing":
        changed.pop("resistance_status")
    else:
        changed["resistance_status"] = status
    assert presentation.torsion_publication_evidence_is_current(inp, None, changed)[0] is False
    rows = presentation.result_summary_rows(inp, {"torsion": changed})
    assert rows and all(row["status"] == "NOT ASSESSED" for row in rows)
    assert all(row["result"] == "-" and row["util"] is None for row in rows)


@pytest.mark.parametrize(("strength", "gamma"), ((240.0, 1.2), (550.0, 2.75)))
def test_review_r2_binds_longitudinal_provision_without_masking_current_resistance(
    torsion_root, strength, gamma,
):
    inp, root = torsion_root
    positive = presentation.torsion_longitudinal_assessment(root, input_payload=inp)
    assert positive["provided_equivalent_area_mm2"] == pytest.approx(5000.0)
    assert positive["demand_ratio"] == pytest.approx(0.5015563636363638)
    changed = copy.deepcopy(inp)
    changed["bar_materials"] = tuple(
        SimpleNamespace(fytk=strength, gamma_y=gamma) for _ in inp["bars"]
    )
    assert presentation.torsion_publication_evidence_is_current(changed, None, root) == (True, None)
    stale = presentation.torsion_longitudinal_assessment(root, input_payload=changed)
    assert stale["status"] == "NOT ASSESSED" and stale["evidence_consistent"] is False
    for key in ("required_asl_mm2", "provided_equivalent_area_mm2", "provided_design_force_kn", "demand_ratio"):
        assert stale[key] is None
    rows = {row["overview_key"]: row for row in presentation.result_summary_rows(changed, {"torsion": root})}
    assert rows["torsion:resistance"]["status"] == "FAIL"
    assert rows["torsion:resistance"]["result"] == "126.9 %"
    assert rows["torsion:longitudinal"]["status"] == "NOT ASSESSED"
    assert rows["torsion:longitudinal"]["result"] == "-"
    fresh = copy.deepcopy(root)
    fresh["longitudinal_assessment"] = capacity.torsion_longitudinal_assessment(
        changed, (root["asl_req"],), resistance_assessed=True,
    )
    assessment = presentation.torsion_longitudinal_assessment(fresh, input_payload=changed)
    assert assessment["status"] == "FAIL"
    assert assessment["provided_equivalent_area_mm2"] == pytest.approx(2181.8181818181815)
    assert assessment["demand_ratio"] == pytest.approx(1.1494)


@pytest.fixture(scope="module", params=(
    pytest.param(("vx", 20.0), id="vx-positive", marks=pytest.mark.xdist_group("vx-positive")),
    pytest.param(("vx", -20.0), id="vx-negative", marks=pytest.mark.xdist_group("vx-negative")),
    pytest.param(("vy", 30.0), id="vy-positive", marks=pytest.mark.xdist_group("vy-positive")),
    pytest.param(("vy", -30.0), id="vy-negative", marks=pytest.mark.xdist_group("vy-negative")),
))
def signed_shear_case(request, tmp_path_factory):
    component, demand = request.param
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path_factory.mktemp("signed-shear") / "autosave"))
        at = _fresh()
        at.run()
        _set(at, ("checkbox", "shear_on", True), ("checkbox", "torsion_on", True), ("checkbox", "shear_links", True), ("checkbox", "combined_on", True))
        _set_and_click(
            at, "calculate", ("number_input", "pl_Mx", 0.0),
            ("number_input", "torsion_T", 40.0),
            ("number_input", "shear_V" + component[-1], demand),
        )
        assert not at.exception
        inp = copy.deepcopy(at.session_state["result_input_snapshot"])
        out = copy.deepcopy(at.session_state["results"])
        (tmp_path_factory.getbasetemp() / f"signed-native-{component}-{demand:g}.pickle").write_bytes(
            pickle.dumps((inp, out)),
        )
        yield {"at": at, "inp": inp, "out": out, "component": component, "demand": demand}


def test_review_r5_real_signed_parent_retains_raw_faces_and_torsion(signed_shear_case):
    case = signed_shear_case
    inp, out, shear = case["inp"], case["out"], case["out"]["shear"]
    assert shear["signed_v_ed"] == case["demand"]
    assert all(face["shear"]["v_ed"] == abs(case["demand"]) for face in shear["face_candidates"])
    assert presentation.directional_shear_publication_evidence_is_current(
        inp, shear, plastic_result=out["plastic"],
    ) == (True, None)
    assert presentation.torsion_publication_evidence_is_current(inp, shear, out["torsion"]) == (True, None)
    assert inp["combined_on"] is True and out["combined"]["dkna_valid"] is True
    assert presentation.combined_publication_evidence_is_current(inp, out) == (True, None)
    stale = copy.deepcopy(out)
    stale["shear"]["signed_v_ed"] *= -1.0
    assert presentation.directional_shear_publication_evidence_is_current(
        inp, stale["shear"], plastic_result=out["plastic"],
    )[0] is False
    assert presentation.combined_publication_evidence_is_current(inp, stale)[0] is False
    changed_input = dict(inp)
    changed_input["shear_V" + case["component"][-1]] *= -1.0
    assert presentation.combined_publication_evidence_is_current(changed_input, out)[0] is False
    _select_view(case["at"], "Shear")
    assert not case["at"].exception
    tables = [item.value for item in case["at"].dataframe]
    assert any("Status / outcome" in table.columns for table in tables)
    assert not any(
        "face-specific shear evidence is unavailable" in str(item.value)
        for item in case["at"].warning
    )
    _select_view(case["at"], "M-V-T Combined")
    assert not case["at"].exception
    dkna = next(item for item in case["at"].metric if "S_{Ed}/S_{Rd}" in item.label)
    assert "".join(str(dkna.value).split()) == f"{100.0 * out['combined']['dkna_sum']:.1f}%"


def test_review_r5_signed_shear_reaches_actual_standard_report(signed_shear_case, tmp_path):
    case = signed_shear_case
    out = copy.deepcopy(case["out"])
    out["worked_example_selection"] = presentation.worked_example_selection(case["inp"], out)
    assert out["worked_example_selection"]["families"].get("shear") is not None
    pdf = sector_report.build_report({}, case["inp"], out, figures=False, profile="Standard")
    label = f"{case['component']}-{case['demand']:g}"
    (tmp_path / f"signed-shear-{label}-Standard.pdf").write_bytes(pdf)
    text = " ".join(" ".join((page.extract_text() or "").split()) for page in PdfReader(io.BytesIO(pdf)).pages)
    assert "Shear resistance" in text
    assert "face-specific shear evidence is unavailable" not in text
    assert "Face-specific shear comparison NOT ASSESSED" not in text
    assert "Candidate face" in text
    assert f"{out['torsion']['trd']:.3f}" in text
    assert "Combined bending + shear + torsion (M-V-T)" in text
    assert f"{100.0 * out['combined']['dkna_sum']:.1f}%" in "".join(text.split())
    assert "combined component evidence is unavailable" not in text


@pytest.mark.parametrize("provision_factor", (0.1, 10.0))
def test_review_r2_combined_rejects_coherent_provision_aliases(
    signed_shear_case, provision_factor,
):
    """Assemble a coherent poison from real native combined face components."""
    case = signed_shear_case
    action, _reason = presentation._current_shear_action_evidence(
        case["inp"], case["out"]["shear"], "unavailable",
    )
    face = case["out"]["shear"]["face_candidates"][0]
    inp = presentation._current_shear_face_input(
        case["inp"], action, face["tension_low"],
    )
    out = copy.deepcopy({
        "plastic": case["out"]["plastic"],
        "shear": face["shear"], "torsion": face["torsion"],
    })
    capacity.finalize_combined(inp, out)
    assert presentation.combined_publication_evidence_is_current(inp, out) == (True, None)
    root = out["torsion"]
    current = presentation.torsion_longitudinal_assessment(root, input_payload=inp)
    assert current["evidence_consistent"] is True
    provided = current["provided_equivalent_area_mm2"]
    assert provided > 0.0
    retained = root["longitudinal_assessment"]
    for key in ("provided_gross_area_mm2", "provided_design_force_kn", "provided_equivalent_area_mm2"):
        retained[key] *= provision_factor
    retained["demand_ratio"] /= provision_factor
    retained["area_sufficient"] = retained["demand_ratio"] <= 1.0
    if retained["area_sufficient"]:
        retained.update(status="NOT ASSESSED", ok=None, reason="longitudinal_torsion_reinforcement_not_verified")
    else:
        retained.update(status="FAIL", ok=False, reason="longitudinal_torsion_reinforcement_insufficient")
    root["assessment_status"] = presentation.torsion_assessment_status(root)
    root["overall_reason"] = retained["reason"]
    capacity.finalize_combined(inp, out)
    assert out["combined"]["torsion_longitudinal_assessment"] == retained
    assert retained["provided_equivalent_area_mm2"] == pytest.approx(provision_factor * provided)
    assert presentation.combined_publication_evidence_is_current(inp, out)[0] is False
    rows = presentation.result_summary_rows(inp, out)
    combined_rows = [row for row in rows if str(row["overview_key"]).startswith("combined")]
    assert combined_rows
    assert all(row["status"] == "NOT ASSESSED" and row["result"] == "-" for row in combined_rows)


@pytest.fixture(scope="module")
def named_zero_shear_case(tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SECTOR_AUTOSAVE_DIR", str(tmp_path_factory.mktemp("named-zero-shear") / "autosave"))
        at = _fresh()
        at.run()
        _set(at, ("checkbox", "shear_on", True), ("checkbox", "torsion_on", True), ("checkbox", "shear_links", True))
        _set(at, ("number_input", "pl_Mx", 0.0), ("number_input", "shear_Vy", 150.0), ("number_input", "torsion_T", 40.0), ("text_input", "pl_case_id", "PL-SHEAR"))
        tables = {key: at.session_state[key] for key in project_io.PROJECT_TABLE_KEYS if key in at.session_state}
        cases = tables["plastic_cases_base"].copy(deep=True)
        cases.loc[1] = cases.loc[0]
        cases.loc[1, "name"] = "PL-ZERO"
        cases.loc[1, "vx_ed_kn"] = 0.0
        cases.loc[1, "vy_ed_kn"] = 0.0
        cases.loc[1, "t_ed_knm"] = 200.0
        tables["plastic_cases_base"] = cases
        scalars = {key: at.session_state[key] for key in project_io.SCALAR_KEYS if key in at.session_state}
        scalars[capacity.TORSION_CASE_AUTHORITIES_KEY] = {
            name: {
                capacity.TORSION_CASE_DESIGN_BASIS_KEY: capacity.TORSION_DESIGN_EQUILIBRIUM,
                capacity.TORSION_CASE_MEMBER_SCOPE_KEY: capacity.TORSION_MEMBER_CLOSED,
            }
            for name in ("PL-SHEAR", "PL-ZERO")
        }
        at.session_state["_pending_project"] = project_io.dump_project(tables, scalars)
        at.run()
        _calculate(at)
        assert not at.exception
        inp = copy.deepcopy(at.session_state["result_input_snapshot"])
        out = copy.deepcopy(at.session_state["results"])
        (tmp_path_factory.getbasetemp() / "named-zero-shear-native.pickle").write_bytes(pickle.dumps((inp, out)))
        assert [entry["name"] for entry in out["plastic_cases"]] == ["PL-SHEAR", "PL-ZERO"]
        local = out["plastic_cases"][1]
        case_inp = case_analysis.plastic_case_input(inp, local["actions"])
        assert out["shear"]["v_ed"] == 150.0
        assert local["results"].get("shear") is None
        assert local["results"]["torsion"]["applicability"]["status"] == "APPLICABLE"
        assert presentation.torsion_publication_component_is_current(case_inp, None, local["results"]["torsion"]) == (True, None)
        yield {"at": at, "inp": inp, "out": out, "case_inp": case_inp, "local": local["results"]}


def test_review_r4_native_later_zero_shear_case_keeps_own_torsion(named_zero_shear_case):
    case = named_zero_shear_case
    at = case["at"]
    _select_view(at, "Torsion")
    at.selectbox(key="_plastic_result_case_index").set_value(1).run()
    assert not at.exception
    root = case["local"]["torsion"]
    assert any(str(item.value) == f"{root['trd']:.3f} kNm" for item in at.metric)
    assert not any("Torsion component evidence is not current" in str(item.value) for item in at.warning)


def test_review_r1_actual_native_view_rejects_false_resistance_pass(named_zero_shear_case):
    case = named_zero_shear_case
    at = case["at"]
    _select_view(at, "Torsion")
    at.selectbox(key="_plastic_result_case_index").set_value(1).run()
    expected_resistance = f"{case['local']['torsion']['trd']:.3f} kNm"
    assert any(str(item.value) == expected_resistance for item in at.metric)
    baseline = copy.deepcopy(at.session_state["results"])
    changed = copy.deepcopy(baseline)
    root = changed["plastic_cases"][1]["results"]["torsion"]
    assert root["resistance_status"] == "FAIL"
    root["resistance_status"] = "PASS"
    try:
        at.session_state["results"] = changed
        at.run()
        assert not at.exception
        assert not any(str(item.value) == expected_resistance for item in at.metric)
        assert at.warning
    finally:
        at.session_state["results"] = baseline
        at.run()


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_review_r4_actual_named_zero_shear_report_keeps_own_torsion(
    named_zero_shear_case, profile, tmp_path,
):
    case = named_zero_shear_case
    out = copy.deepcopy(case["out"])
    out["worked_example_selection"] = presentation.worked_example_selection(case["inp"], out)
    pdf = sector_report.build_report({}, case["inp"], out, figures=False, profile=profile)
    (tmp_path / f"named-zero-shear-{profile}.pdf").write_bytes(pdf)
    text = " ".join(" ".join((page.extract_text() or "").split()) for page in PdfReader(io.BytesIO(pdf)).pages)
    root = case["local"]["torsion"]
    assert f"Torsion transverse/strut resistance PL-ZERO {root['resistance_status']} {100.0 * root['util']:.1f} %" in text
    if profile != "Brief":
        assert f"{root['trd']:.3f}" in text
        assert "Torsion (thin-walled tube) - PL-ZERO" in text


def test_review_r2_actual_native_longitudinal_body_withholds_changed_strength(named_zero_shear_case):
    case = named_zero_shear_case
    changed = copy.deepcopy(case["case_inp"])
    changed["bar_materials"] = tuple(
        replace(material, fytk=24.0) for material in changed["bar_materials"]
    )
    harness = AppTest.from_string(
        "import streamlit as st\nimport sector_app\n"
        "sector_app.torsion_view(st.session_state['review_input'], st.session_state['review_output'])\n",
        default_timeout=90,
    )
    harness.session_state["review_input"] = changed
    harness.session_state["review_output"] = copy.deepcopy(case["local"])
    harness.run(timeout=90)
    assert not harness.exception
    root = case["local"]["torsion"]
    assert any(str(item.value) == f"{root['trd']:.3f} kNm" for item in harness.metric)
    longitudinal = next(
        item.value for item in harness.dataframe
        if "Quantity" in item.value and "Longitudinal assessment" in set(item.value["Quantity"])
    )
    assert longitudinal["Value"].tolist() == ["-", "-", "-", "NOT ASSESSED"]


@pytest.mark.parametrize("attack", ("status", "strength"))
@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_review_r1_r2_actual_report_withholds_poisoned_torsion(
    named_zero_shear_case, attack, profile, tmp_path,
):
    case = named_zero_shear_case
    inp, out = copy.deepcopy(case["inp"]), copy.deepcopy(case["out"])
    root = out["plastic_cases"][1]["results"]["torsion"]
    if attack == "status":
        assert root["resistance_status"] == "FAIL"
        root["resistance_status"] = "PASS"
    else:
        inp["bar_materials"] = tuple(
            replace(material, fytk=24.0) for material in inp["bar_materials"]
        )
    # Brief retains one governing row per check; an equal unassessed first case
    # remains selected. Independently require the poisoned case's own row to
    # withhold its values before checking each profile's published selection.
    key = "torsion" if attack == "status" else "torsion:longitudinal"
    local_rows = presentation.result_summary_rows(
        case_analysis.plastic_case_input(inp, out["plastic_cases"][1]["actions"]),
        out["plastic_cases"][1]["results"],
    )
    rejected = next(row for row in local_rows if row["overview_key"] == key)
    assert rejected["status"] == "NOT ASSESSED"
    assert rejected["result"] == "-" and rejected["util"] is None
    out["worked_example_selection"] = presentation.worked_example_selection(inp, out)
    pdf = sector_report.build_report({}, inp, out, figures=False, profile=profile)
    (tmp_path / f"torsion-{attack}-{profile}.pdf").write_bytes(pdf)
    text = " ".join(" ".join((page.extract_text() or "").split()) for page in PdfReader(io.BytesIO(pdf)).pages)
    compact = "".join(text.split())
    if attack == "status":
        if profile == "Brief":
            assert "TorsionPL-SHEARNOTASSESSEDNOTASSESSED" in compact
        else:
            assert "TorsionPL-ZERONOTASSESSED-" in compact
        assert "Torsiontransverse/strutresistancePL-ZEROPASS" not in compact
    else:
        assert "TorsionlongitudinalreinforcementPL-ZERONOTASSESSED-" in compact
        assert (
            "Torsiontransverse/strutresistancePL-ZEROFAIL"
            f"{100.0 * root['util']:.1f}%"
        ) in compact
