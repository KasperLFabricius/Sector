"""PUB-M01 native controls for the actual torsion angle participants."""

from __future__ import annotations

import copy
import io
from pathlib import Path
import pickle
import sys

from pypdf import PdfReader
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "tests")]

import result_presentation as presentation  # noqa: E402
import sector_report  # noqa: E402
from sector import shear as shear_core  # noqa: E402
from test_torsion import (  # noqa: E402
    _calculate,
    _fresh,
    _select_view,
    _set,
    _set_and_click,
    _subdivided,
)

pytestmark = pytest.mark.xdist_group("publication_participants")


@pytest.fixture(scope="module", params=(
    "torsion-only", "zero-shear", "invalid-shear",
    pytest.param("biaxial", id="biaxial", marks=pytest.mark.xdist_group("biaxial")),
    pytest.param("biaxial-no-links", id="biaxial-no-links", marks=pytest.mark.xdist_group("biaxial-no-links")),
    "subdivided",
))
def current_participants(request, tmp_path_factory):
    """Produce each control through real inputs, Calculate and native views."""
    name = request.param
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(
            "SECTOR_AUTOSAVE_DIR",
            str(tmp_path_factory.mktemp("participants-" + name) / "autosave"),
        )
        at = _fresh()
        at.run()
        if name == "subdivided":
            _subdivided(at)
            _calculate(at)
        else:
            _set(
                at,
                ("checkbox", "shear_on", name != "torsion-only"),
                ("checkbox", "torsion_on", True),
                ("checkbox", "shear_links", name != "biaxial-no-links"),
            )
            changes = [
                ("number_input", "pl_Mx", 0.0),
                ("number_input", "torsion_T", 40.0),
            ]
            if name not in {"torsion-only", "zero-shear"}:
                changes.append(("number_input", "shear_Vy", 30.0))
            if name.startswith("biaxial"):
                changes.append(("number_input", "shear_Vx", 20.0))
            if name == "invalid-shear":
                changes.append((
                    "selectbox", "shear_section_form",
                    shear_core.SHEAR_SECTION_VARIABLE,
                ))
            _set_and_click(at, "calculate", *changes)
        assert not at.exception
        inp = copy.deepcopy(at.session_state["result_input_snapshot"])
        out = copy.deepcopy(at.session_state["results"])
        (tmp_path_factory.getbasetemp() / f"participant-native-{name}.pickle").write_bytes(
            pickle.dumps((inp, out)),
        )
        out["worked_example_selection"] = presentation.worked_example_selection(inp, out)
        _select_view(at, "Torsion")
        assert not at.exception
        metrics = [(item.label, str(item.value)) for item in at.metric]
        tables = [item.value.copy(deep=True) for item in at.dataframe]
        visible = " ".join(
            str(item.value)
            for collection in (at.caption, at.markdown, at.warning, at.info)
            for item in collection
        )
        _select_view(at, "Results Overview")
        assert not at.exception
        overview = next(
            item.value.copy(deep=True) for item in at.table
            if "Check" in item.value.columns
        )
        yield {
            "name": name, "at": at, "inp": inp, "out": out,
            "metrics": metrics, "tables": tables,
            "visible": visible, "overview": overview,
        }


def test_pub_m01_current_participants_retain_independent_native_evidence(
    current_participants,
):
    case = current_participants
    inp, out = case["inp"], case["out"]
    t = out["torsion"]
    assert presentation.torsion_publication_evidence_is_current(
        inp, out.get("shear"), t,
    ) == (True, None)
    if case["name"] == "biaxial-no-links":
        assert t["member_angle_selection"] is None
        assert t["theta_mode"] == "transparency"
        assert t["trd"] is None and t["util"] is None
        screen = next(
            table for table in case["tables"]
            if "Directional 6.31 screen" in table.columns
        )
        assert set(screen["Directional 6.31 screen"]) == {
            "Vx,Ed + TEd", "Vy,Ed + TEd",
        }
        assert set(screen["Status"]) <= {"PASS", "FAIL"}
    else:
        assert t["member_angle_selection"] is not None
        assert t["theta_mode"] == "utilisation"
        assert all(
            label.startswith("torsion sub-tube ")
            for label in t["member_angle_selection"]["objective_labels"]
        )
        assert (
            "The member strut angle minimises the governing torsion utilisation "
            "across the active sub-tubes."
        ) in case["visible"]
        assert t["primary"]["cot"] == pytest.approx(t["cot"])
        assert any(
            value == f"{t['trd']:.3f} kNm" for _label, value in case["metrics"]
        )
        row = case["overview"].loc[
            case["overview"]["Check"] == "Torsion transverse/strut resistance"
        ].iloc[0]
        assert row["Status"] == t["resistance_status"]
        assert row["Result"] == f"{100.0 * t['util']:.1f} %"
    if case["name"] in {"torsion-only", "zero-shear"}:
        assert out.get("shear") is None
        assert t["subtubes"] is None
    if case["name"] == "zero-shear":
        import sector_app

        legacy_alias_input = copy.deepcopy(inp)
        legacy_alias_input["shear_V"] = 150.0
        reproduced = {"plastic": copy.deepcopy(out["plastic"])}
        sector_app._run_capacity_checks(legacy_alias_input, reproduced)
        assert reproduced.get("shear") is None
        assert reproduced["torsion"]["member_angle_selection"] == t["member_angle_selection"]
        assert presentation.torsion_publication_evidence_is_current(
            legacy_alias_input, None, reproduced["torsion"],
        ) == (True, None)
    if case["name"] == "invalid-shear":
        assert out["shear"]["res"]["valid"] is False
        assert t["primary"]["transverse_resistance_assessed"] is True
    if case["name"].startswith("biaxial"):
        assert out["shear"].get("links") is None
        assert set(t["directional_interactions"]) == {"vx", "vy"}
        for child in out["shear"]["directions"].values():
            assert presentation.directional_shear_publication_evidence_is_current(
                inp, child, plastic_result=out["plastic"],
            ) == (True, None)
            if case["name"] == "biaxial-no-links":
                assert all(face["torsion_status"] == "NOT ASSESSED" for face in child["face_candidates"])
                poisoned_child = copy.deepcopy(child)
                poisoned_child["face_candidates"][0]["torsion_status"] = "NOT RUN"
                assert presentation.directional_shear_publication_evidence_is_current(
                    inp, poisoned_child, plastic_result=out["plastic"],
                )[0] is False
        shear_selection = presentation.worked_example_selection(inp, out)["families"]["shear"]
        expected_direction = max(
            ("vx", "vy"),
            key=lambda component: out["shear"]["directions"][component]["nominal_resistance"]["utilisation"],
        )
        assert shear_selection == {"case_id": "PL-01", "component": expected_direction}
        poisoned = copy.deepcopy(out)
        changed_child = poisoned["shear"]["directions"][expected_direction]
        changed_child["signed_v_ed"] += 1.0
        remaining = "vy" if expected_direction == "vx" else "vx"
        assert presentation._transverse_direction(
            "shear", poisoned["shear"], input_payload=inp,
            shear_result=poisoned["shear"], torsion_result=t,
            plastic_result=out["plastic"],
        ) is None
        # A changed action invalidates wrapper identity. A poisoned quantitative
        # alias within an otherwise current wrapper withholds only that child.
        poisoned = copy.deepcopy(out)
        poisoned["shear"]["directions"][expected_direction]["nominal_resistance"]["resistance"] += 1.0
        assert presentation._transverse_direction(
            "shear", poisoned["shear"], input_payload=inp,
            shear_result=poisoned["shear"], torsion_result=t,
            plastic_result=out["plastic"],
        ) == remaining
        assert presentation._single_torsion_publication_evidence_is_current(
            t, presentation._current_torsion_only_children(inp),
        ) == (True, None)
    if case["name"] == "subdivided":
        subs = t["subtubes"]
        assert len(subs) == 2
        assert subs[0]["t_ed"] != pytest.approx(subs[1]["t_ed"])
        assert t["t_ed"] == pytest.approx(sum(item["t_ed"] for item in subs))
        assert t["trd"] == pytest.approx(sum(item["trd"] for item in subs))
        assert t["asl_req"] == pytest.approx(sum(item["asl_req"] for item in subs))
        assert t["util"] == pytest.approx(max(item["util"] for item in subs))


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_pub_m01_current_participants_reach_actual_report_routes(
    current_participants, profile, tmp_path,
):
    case = current_participants
    inp, out = case["inp"], case["out"]
    t = out["torsion"]
    pdf = sector_report.build_report(
        {}, inp, copy.deepcopy(out), figures=False, profile=profile,
    )
    (tmp_path / f"participants-{case['name']}-{profile}.pdf").write_bytes(pdf)
    # Join body paragraphs across pages without inserting the repeated footer.
    text = " ".join(
        " ".join((page.extract_text() or "").split("\nProject:", 1)[0].split())
        for page in PdfReader(io.BytesIO(pdf)).pages
    )
    if t["transverse_resistance_assessed"]:
        assert (
            "Torsion transverse/strut resistance PL-01 "
            f"{t['resistance_status']} {100.0 * t['util']:.1f} %"
        ) in text
        if profile != "Brief":
            assert f"{t['trd']:.3f}" in text
            assert "Torsion (thin-walled tube)" in text
            assert (
                "The member strut angle minimises the governing torsion utilisation "
                "across the active sub-tubes."
            ) in text
    else:
        # The narrow Standard overview column wraps inside the long label.
        compact = "".join(text.split())
        assert "Vx+TFormula(6.31)minimum-reinforcementscreen" in compact
        assert "Vy+TFormula(6.31)minimum-reinforcementscreen" in compact
        for component in ("vx", "vy"):
            minimum = t["directional_interactions"][component]["min_reinf"]
            assert f"{100.0 * minimum['value']:.1f} %" in text
    if profile == "Audit" and t.get("directional_interactions"):
        selected = out["worked_example_selection"]["torsion_subchecks"]
        assert selected["minimum_reinforcement"]["component"] in {"vx", "vy"}
    if case["name"].startswith("biaxial") and profile != "Brief":
        selected = out["worked_example_selection"]["families"]["shear"]
        component = selected["component"][-1]
        assert f"Governingworkedexample:V{component},Ed" in "".join(text.split())
        assert "Worked shear calculation unavailable" not in text
        assert "Face-specific shear comparison NOT ASSESSED" not in text
        assert "Candidate face" in text
        child = out["shear"]["directions"][selected["component"]]
        for face in child["face_candidates"]:
            label = sector_report.viz.tension_face_label(face["tension_low"], child["axis"])
            expected = f"{label}{face['shear']['res']['vrd_c']:.3f}kN"
            assert "".join(expected.split()) in "".join(text.split())


def test_pub_m01_participant_records_cannot_authorize_missing_or_changed_evidence(
    current_participants,
):
    case = current_participants
    inp, out = case["inp"], case["out"]
    original = out["torsion"]
    attacks = []
    if original["member_angle_selection"] is not None:
        for value in (None, "missing"):
            mutated = copy.deepcopy(original)
            if value == "missing":
                mutated.pop("member_angle_selection")
            else:
                mutated["member_angle_selection"] = value
            attacks.append(mutated)
        for value in (None, "resistance", "transparency"):
            mutated = copy.deepcopy(original)
            mutated["theta_mode"] = value
            attacks.append(mutated)
    if original.get("directional_interactions"):
        for component in ("vx", "vy"):
            mutated = copy.deepcopy(original)
            child = mutated["directional_interactions"][component]
            child["min_reinf"]["value"] = 876.543
            attacks.append(mutated)
            if child["member_angle_selection"] is not None:
                mutated = copy.deepcopy(original)
                mutated["directional_interactions"][component][
                    "member_angle_selection"
                ] = None
                attacks.append(mutated)
    if original.get("subdivided"):
        for key in ("trd", "asl_req", "t_ed"):
            mutated = copy.deepcopy(original)
            mutated[key] = mutated["primary"][key]
            attacks.append(mutated)
    else:
        mutated = copy.deepcopy(original)
        mutated["subtubes"] = [copy.deepcopy(original["primary"])]
        attacks.append(mutated)
    assert attacks
    for mutated in attacks:
        assert presentation.torsion_publication_evidence_is_current(
            inp, out.get("shear"), mutated,
        ) == (False, "torsion result evidence is unavailable")


def _poison_participant(case):
    out = copy.deepcopy(case["out"])
    targets = [out, *[item["results"] for item in out.get("plastic_cases", ())]]
    for target in targets:
        t = target["torsion"]
        if t.get("directional_interactions"):
            child = t["directional_interactions"]["vy"]
            child["min_reinf"]["value"] = 876.543
            if child.get("interaction") is not None:
                child["interaction"]["value"] = 947.321
        elif t.get("subdivided"):
            t["trd"] = t["primary"]["trd"]
        else:
            t["member_angle_selection"] = None
    out["worked_example_selection"] = presentation.worked_example_selection(case["inp"], out)
    return out


def test_pub_m01_poisoned_participant_is_withheld_in_native_views(
    current_participants,
):
    case = current_participants
    at = case["at"]
    baseline = copy.deepcopy(at.session_state["results"])
    poisoned = _poison_participant(case)
    try:
        at.session_state["results"] = poisoned
        _select_view(at, "Torsion")
        assert not at.exception
        t = case["out"]["torsion"]
        if t.get("directional_interactions"):
            screen = next(
                item.value for item in at.dataframe
                if "Directional 6.31 screen" in item.value.columns
            )
            by_component = screen.set_index("Directional 6.31 screen")
            assert by_component.loc["Vy,Ed + TEd", "Status"] == "NOT ASSESSED"
            assert by_component.loc["Vx,Ed + TEd", "Status"] in {"PASS", "FAIL"}
            if t["transverse_resistance_assessed"]:
                assert any(str(item.value) == f"{t['trd']:.3f} kNm" for item in at.metric)
        else:
            assert any(str(item.value) == "NOT ASSESSED" for item in at.metric)
            assert not any(str(item.value) == f"{t['trd']:.3f} kNm" for item in at.metric)
        all_visible = " ".join(
            str(item.value) for collection in (
                at.metric, at.dataframe, at.caption, at.markdown, at.info, at.warning,
            ) for item in collection
        )
        assert "876.543" not in all_visible and "947.321" not in all_visible
        _select_view(at, "Results Overview")
        assert not at.exception
        overview = next(item.value for item in at.table if "Check" in item.value.columns)
        if t.get("directional_interactions"):
            row = overview.loc[
                overview["Check"] == "Vy+T Formula (6.31) minimum-reinforcement screen"
            ].iloc[0]
            assert row["Status"] == "NOT ASSESSED" and row["Result"] == "-"
        else:
            row = overview.loc[overview["Check"] == "Torsion"].iloc[0]
            assert row["Status"] == "NOT ASSESSED" and row["Result"] == "-"
    finally:
        at.session_state["results"] = baseline
        at.run()


@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
def test_pub_m01_poisoned_participant_is_withheld_from_actual_reports(
    current_participants, profile, tmp_path,
):
    case = current_participants
    out = _poison_participant(case)
    t = case["out"]["torsion"]
    pdf = sector_report.build_report({}, case["inp"], out, figures=False, profile=profile)
    (tmp_path / f"poisoned-{case['name']}-{profile}.pdf").write_bytes(pdf)
    text = " ".join(
        " ".join((page.extract_text() or "").split())
        for page in PdfReader(io.BytesIO(pdf)).pages
    )
    assert "876.543" not in text and "947.321" not in text
    assert "87654.3" not in text and "94732.1" not in text
    if t.get("directional_interactions"):
        compact = "".join(text.split())
        assert "Vy+TFormula(6.31)minimum-reinforcementscreen" in compact
        if t["transverse_resistance_assessed"]:
            assert (
                "Torsion transverse/strut resistance PL-01 "
                f"{t['resistance_status']} {100.0 * t['util']:.1f} %"
            ) in text
        assert all(
            selected["component"] != "vy"
            for selected in out["worked_example_selection"]["torsion_subchecks"].values()
        )
    else:
        assert "Torsion PL-01 NOT ASSESSED -" in text
