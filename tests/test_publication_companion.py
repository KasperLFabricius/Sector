"""Real direct producer and consumer controls for same-case torsion evidence."""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import io
from pathlib import Path
import pickle
import sys

from pypdf import PdfReader
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "tests")]

import result_presentation as presentation
import sector_report
from test_torsion import _fresh, _set, _set_and_click

pytestmark = pytest.mark.xdist_group("publication_companion")


def test_publication_solve_scope_tracks_typed_input_and_lifetime():
    calls = []

    def solve(inp):
        calls.append(copy.deepcopy(inp))
        return float(len(calls)), True

    inp = {"action": 1.0, "bar": [20.0]}
    with presentation.publication_calculation_scope():
        first = presentation._publication_solver_result(solve, inp)
        with presentation.publication_calculation_scope():
            assert presentation._publication_solver_result(solve, copy.deepcopy(inp)) == first
        inp["bar"][0] = 25.0
        assert presentation._publication_solver_result(solve, inp) == (2.0, True)
        inp["action"] = False
        assert presentation._publication_solver_result(solve, inp) == (3.0, True)
        inp["action"] = 0.0
        assert presentation._publication_solver_result(solve, inp) == (4.0, True)
        copied = copy_context()
    assert presentation._PUBLICATION_SOLVES.get() is None

    def evaluate():
        with presentation.publication_calculation_scope():
            return presentation._publication_solver_result(solve, inp)

    assert copied.run(evaluate) == (5.0, True)
    assert copied.run(evaluate) == (6.0, True)
    with pytest.raises(RuntimeError, match="scope exit"):
        with presentation.publication_calculation_scope():
            assert evaluate() == (7.0, True)
            raise RuntimeError("scope exit")
    assert evaluate() == (8.0, True)


def test_publication_solve_scope_isolates_copied_threads():
    calls = []

    def solve(inp):
        calls.append(inp)
        return float(len(calls)), True

    def evaluate():
        with presentation.publication_calculation_scope():
            first = presentation._publication_solver_result(solve, {})
            assert presentation._publication_solver_result(solve, {}) == first
            return first

    with presentation.publication_calculation_scope():
        assert evaluate() == (1.0, True)
        copied = copy_context()
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(copied.run, evaluate).result() == (2.0, True)
        assert evaluate() == (1.0, True)


def test_publication_solve_scope_rechecks_seams_and_input_after_miss(monkeypatch):
    inp = {"action": 1.0}
    calls = []

    def mutate(data):
        calls.append(data["action"])
        data["action"] += 1.0
        return float(len(calls)), True

    with presentation.publication_calculation_scope():
        assert presentation._publication_solver_result(mutate, inp) == (1.0, True)
        inp["action"] = 1.0
        assert presentation._publication_solver_result(mutate, inp) == (2.0, True)

    def solve(data):
        return presentation.capacity.conditional_capacity(data), True

    with presentation.publication_calculation_scope():
        monkeypatch.setattr(presentation.capacity, "conditional_capacity", lambda data: 10.0)
        assert presentation._publication_solver_result(solve, inp) == (10.0, True)
        monkeypatch.setattr(presentation.capacity, "conditional_capacity", lambda data: 20.0)
        assert presentation._publication_solver_result(solve, inp) == (20.0, True)


def test_publication_solve_scope_bypasses_custom_and_mutable_state():
    reducer_calls = []

    class CustomInput:
        value = 1.0

        def __reduce__(self):
            reducer_calls.append(self)
            raise AssertionError("custom reducer must not execute")

    custom = CustomInput()
    with presentation.publication_calculation_scope():
        def solve(inp):
            return inp["custom"].value, True

        assert presentation._publication_solver_result(solve, {"custom": custom}) == (1.0, True)
        custom.value = 2.0
        assert presentation._publication_solver_result(solve, {"custom": custom}) == (2.0, True)

        def mutable(inp):
            return 1.0, []

        first = presentation._publication_solver_result(mutable, {})
        first[1].append("changed")
        assert presentation._publication_solver_result(mutable, {}) == (1.0, [])
    assert reducer_calls == []


@pytest.mark.parametrize("location", (
    "numpy_metadata", "index_name", "column_name", "declared_metadata", "extension_dtype",
))
def test_publication_solve_scope_bypasses_custom_table_state(location):
    import numpy as np
    import pandas as pd

    reducer_calls = []

    class CustomMetadata:
        def __reduce__(self):
            reducer_calls.append(self)
            return str, ("hidden state",)

    custom = CustomMetadata()
    value = pd.DataFrame({"load": [1.0]})
    if location == "numpy_metadata":
        value = np.array([1.0], dtype=np.dtype("float64", metadata={"state": custom}))
    elif location == "index_name":
        value.index.name = custom
    elif location == "column_name":
        value.columns.name = custom
    elif location == "declared_metadata":
        value._metadata = ["extra"]
        object.__setattr__(value, "extra", custom)
    else:
        value["load"] = pd.Categorical(["low"])
    calls = []

    def solve(inp):
        calls.append(inp)
        return float(len(calls)), True

    with presentation.publication_calculation_scope():
        assert presentation._publication_solver_result(solve, {"table": value}) == (1.0, True)
        assert presentation._publication_solver_result(solve, {"table": value}) == (2.0, True)
    assert reducer_calls == []


@pytest.mark.parametrize("axis,extra,expected", (
    ("x", {}, [("y", "-30.000 kN")]),
    ("y", {}, [("x", "-30.000 kN")]),
    ("x", {"shear_Vx": 90.0, "shear_Vy": 80.0, "shear_components": {
        "vx": {"signed_v_ed": -20.0}, "vy": {"signed_v_ed": 150.0},
    }}, [("x", "-20.000 kN"), ("y", "150.000 kN")]),
))
def test_direct_member_actions_without_plastic_result(axis, extra, expected):
    inp = dict(
        plastic_case={"id": "PL-DIRECT", "type": "", "source": ""},
        P_pl=-200.0, Mx_pl=25.0, My_pl=-10.0,
        shear_on=True, shear_axis=axis, shear_V=-30.0,
        torsion_on=True, torsion_T=40.0, torsion_T_signed=-10.0,
        **extra,
    )
    builder = object.__new__(sector_report.ReportBuilder)
    builder._base_inp, builder._base_out = inp, {}
    rows = []
    builder._small = lambda *args, **kwargs: None
    builder._table = lambda table, *args, **kwargs: rows.extend(table)
    builder._loads_block()
    assert ["PL-DIRECT - member inputs", "-200.000", "25.000", "-10.000"] in rows
    for component, value in expected:
        assert ["PL-DIRECT", f"Shear V<sub>{component},Ed</sub>", value] in rows
    assert ["PL-DIRECT", "Torsion T<sub>Ed</sub>", "-40.000 kNm"] in rows


@pytest.mark.parametrize("torque,sense", (
    (40.0, None), (40.0, float("nan")), (float("inf"), 40.0), (True, 1.0),
))
def test_direct_actions_keep_unavailable_torque_value_free(torque, sense):
    builder = object.__new__(sector_report.ReportBuilder)
    builder._base_inp = {
        "plastic_case": {"id": "PL-DIRECT", "type": "", "source": ""},
        "torsion_on": True, "torsion_T": torque, "torsion_T_signed": sense,
    }
    builder._base_out = {}
    rows = []
    builder._small = lambda *args, **kwargs: None
    builder._table = lambda table, *args, **kwargs: rows.extend(table)
    builder._loads_block()
    assert ["PL-DIRECT", "Torsion T<sub>Ed</sub>", "- kNm"] in rows


@pytest.fixture(scope="module")
def direct_torsion_cases(tmp_path_factory):
    """Calculate natively, then exercise the supported direct member producer.

    N/M, geometry and materials are unchanged, so both direct V cases reuse the
    actual Plastic result. All member, face-capacity and arm solvers remain real.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(
            "SECTOR_AUTOSAVE_DIR",
            str(tmp_path_factory.mktemp("direct-companion") / "autosave"),
        )
        at = _fresh()
        at.run()
        _set(
            at,
            ("checkbox", "shear_on", True),
            ("checkbox", "torsion_on", True),
            ("checkbox", "shear_links", True),
            ("checkbox", "combined_on", True),
        )
        _set_and_click(
            at, "calculate", ("number_input", "pl_Mx", 0.0),
            ("number_input", "torsion_T", 40.0),
            ("number_input", "shear_Vy", 30.0),
        )
        assert not at.exception
        native_input = copy.deepcopy(at.session_state["result_input_snapshot"])
        native_output = copy.deepcopy(at.session_state["results"])
        import sector_app

        cases = {"native": (native_input, native_output)}
        for demand in (30.0, 150.0):
            inp = copy.deepcopy(native_input)
            for key in ("shear_Vx", "shear_Vy", "shear_components"):
                inp.pop(key, None)
            inp.update(
                shear_axis="x", shear_tension=True, shear_V=demand,
                shear_bw=0.0, shear_link_legs=2.0,
            )
            out = {"plastic": copy.deepcopy(native_output["plastic"])}
            sector_app._run_capacity_checks(inp, out)
            assert "face_candidates" not in out["shear"]
            assert len(out["shear"]["links"]["chord_candidates"]) == 4
            (tmp_path_factory.getbasetemp() / f"direct-companion-{demand:g}.pickle").write_bytes(
                pickle.dumps((inp, out)),
            )
            cases[demand] = (inp, out)
        yield cases


def _companion_case(cases, demand, attack="current"):
    inp, out = copy.deepcopy(cases[demand])
    if attack == "missing":
        out.pop("torsion")
    elif attack == "empty":
        out["torsion"] = {}
    elif attack == "stale":
        out["torsion"]["primary"]["asl_req"] *= 1.10
    elif attack == "wrong_action":
        out["torsion"]["t_ed"] += 10.0
        out["torsion"]["t_ed_signed"] += 10.0
    else:
        assert attack == "current"
    return inp, out


def test_same_scope_rechecks_retained_and_current_input(direct_torsion_cases, monkeypatch):
    inp, out = _companion_case(direct_torsion_cases, 150.0)
    assert isinstance(presentation._publication_key_bytes((inp,), {}), bytes)
    solve = presentation.capacity.shear_face_mrd
    calls = []

    def counted_solve(*args, **kwargs):
        calls.append(None)
        return solve(*args, **kwargs)

    monkeypatch.setattr(presentation.capacity, "shear_face_mrd", counted_solve)
    with presentation.publication_calculation_scope():
        assert presentation.provided_link_publication_assessment(
            inp, out["shear"], torsion_result=out["torsion"],
        ).valid is True
        count = len(calls)
        assert count > 0 and presentation._PUBLICATION_SOLVES.get().cache
        assert presentation.provided_link_publication_assessment(
            inp, out["shear"], torsion_result=out["torsion"],
        ).valid is True
        assert len(calls) == count
        changed = copy.deepcopy(out)
        changed["shear"]["links"]["res"]["vrd"] += 1.0
        rejected = presentation.provided_link_publication_assessment(
            inp, changed["shear"], torsion_result=changed["torsion"],
        )
        assert rejected.valid is False
        assert rejected.resistance is None and rejected.utilisation is None
        changed = copy.deepcopy(out)
        changed["torsion"]["primary"]["asl_req"] *= 1.1
        rejected = presentation.provided_link_publication_assessment(
            inp, changed["shear"], torsion_result=changed["torsion"],
        )
        assert rejected.valid is False
        assert rejected.resistance is None and rejected.utilisation is None
        inp["P_pl"] += 10.0
        rejected = presentation.provided_link_publication_assessment(
            inp, out["shear"], torsion_result=out["torsion"],
        )
        assert rejected.valid is False
        assert rejected.resistance is None and rejected.utilisation is None


@pytest.mark.parametrize("demand", (30.0, 150.0))
def test_direct_same_case_companion_reaches_publication(direct_torsion_cases, demand):
    inp, out = _companion_case(direct_torsion_cases, demand)
    shear, torsion = out["shear"], out["torsion"]
    links = shear["links"]
    provided = presentation.provided_link_publication_assessment(
        inp, shear, torsion_result=torsion,
    )
    assert provided.valid is True
    assert provided.resistance == pytest.approx(links["res"]["vrd"])
    assert provided.utilisation == pytest.approx(demand / provided.resistance)
    assert presentation.shear_publication_input_is_current(
        inp, shear, plastic_result=out["plastic"], torsion_result=torsion,
    ) == (True, None)
    assert presentation.shear_direction_publication_input_is_current(
        inp, shear, plastic_result=out["plastic"], torsion_result=torsion,
    ) == (True, None)
    nominal = presentation.nominal_shear_resistance(
        shear, links_selected=True, input_payload=inp, torsion_result=torsion,
    )
    assert nominal["valid"] is True
    assert nominal["route"] == ("concrete" if demand == 30.0 else "links")
    basis = presentation.shear_geometry_basis(inp, shear, torsion_result=torsion)
    assert basis["z_mm"] == pytest.approx(links["res"]["z"])
    rows = {row["overview_key"]: row for row in presentation.result_summary_rows(inp, out)}
    assert rows["shear:with_links"]["status"] == provided.status
    assert rows["shear:with_links"]["util"] == pytest.approx(provided.utilisation)
    assert presentation.worked_example_selection(inp, out)["families"]["shear"] is not None

    # Native directional results can still recover their own matching face child.
    native_input, native_output = direct_torsion_cases["native"]
    assert presentation.provided_link_publication_assessment(
        native_input, native_output["shear"],
    ).valid is True


@pytest.mark.parametrize("demand", (30.0, 150.0))
@pytest.mark.parametrize("attack", ("missing", "empty", "stale", "wrong_action"))
def test_direct_rejects_unavailable_companion(direct_torsion_cases, demand, attack):
    inp, out = _companion_case(direct_torsion_cases, demand, attack)
    provided = presentation.provided_link_publication_assessment(
        inp, out["shear"], torsion_result=out.get("torsion"),
    )
    assert provided.valid is False and provided.status == "NOT ASSESSED"
    assert provided.resistance is None and provided.utilisation is None
    basis = presentation.shear_geometry_basis(
        inp, out["shear"], torsion_result=out.get("torsion"),
    )
    assert basis["z_mm"] is None
    rows = {row["overview_key"]: row for row in presentation.result_summary_rows(inp, out)}
    assert rows["shear:with_links"]["status"] == "NOT ASSESSED"
    assert rows["shear:with_links"]["result"] == "-"
    assert rows["shear:with_links"]["util"] is None
    if demand == 30.0:
        assert rows["shear:without_links"]["status"] == "PASS"
        assert rows["shear:without_links"]["util"] == pytest.approx(out["shear"]["util"])


@pytest.mark.parametrize("attack", ("missing", "invalid", "ambiguous"))
def test_directional_companion_requires_its_selected_face(direct_torsion_cases, attack):
    inp, out = copy.deepcopy(direct_torsion_cases["native"])
    shear = out["shear"]
    selected = next(
        face for face in shear["face_candidates"]
        if face["tension_low"] is shear["tension_low"]
    )
    # Even a genuine, numerically matching same-case companion cannot replace
    # the directional result's missing or ambiguous selected-face owner.
    companion = copy.deepcopy(selected["torsion"])
    assert presentation.provided_link_publication_assessment(
        inp, shear, torsion_result=companion,
    ).valid is True
    if attack == "missing":
        selected.pop("torsion")
    elif attack == "invalid":
        selected["torsion"] = []
    else:
        shear["face_candidates"].append(copy.deepcopy(selected))
    provided = presentation.provided_link_publication_assessment(
        inp, shear, torsion_result=companion,
    )
    assert provided.valid is False and provided.status == "NOT ASSESSED"
    assert provided.resistance is None and provided.utilisation is None
    assert presentation.shear_geometry_basis(
        inp, shear, torsion_result=companion,
    )["z_mm"] is None
    out["torsion"] = companion
    rows = {row["overview_key"]: row for row in presentation.result_summary_rows(inp, out)}
    assert rows["shear:with_links"]["status"] == "NOT ASSESSED"
    assert rows["shear:with_links"]["util"] is None
    if attack != "ambiguous":
        assert rows["shear:without_links"]["status"] == "PASS"


@pytest.mark.parametrize("demand", (30.0, 150.0))
@pytest.mark.parametrize("attack", ("current", "missing", "stale"))
def test_direct_native_consumer(direct_torsion_cases, demand, attack):
    inp, out = _companion_case(direct_torsion_cases, demand, attack)
    harness = AppTest.from_string(
        "import streamlit as st\nimport sector_app\n"
        "sector_app.shear_view(st.session_state['review_input'], st.session_state['review_output'])\n",
        default_timeout=90,
    )
    harness.session_state["review_input"] = inp
    harness.session_state["review_output"] = out
    harness.run(timeout=90)
    assert not harness.exception
    resistance = f"{out['shear']['links']['res']['vrd']:.3f} kN"
    metrics = [str(item.value) for item in harness.metric]
    if attack == "current":
        assert resistance in metrics
        assert not any("provided-link resistance is NOT ASSESSED" in str(item.value) for item in harness.warning)
    else:
        assert resistance not in metrics
        assert any("NOT ASSESSED" in str(item.value) for item in harness.warning)


@pytest.mark.parametrize("demand", (30.0, 150.0))
@pytest.mark.parametrize("profile", ("Brief", "Standard", "Audit"))
@pytest.mark.parametrize("attack", ("current", "stale"))
def test_direct_report_consumer(direct_torsion_cases, demand, profile, attack, tmp_path):
    inp, out = _companion_case(direct_torsion_cases, demand, attack)
    # This consumer exercises the direct inp/out API. A declared case ledger
    # without matching output entries correctly means those cases are unrun.
    inp.pop("plastic_cases")
    inp.pop("elastic_cases")
    out["worked_example_selection"] = presentation.worked_example_selection(inp, out)
    pdf = sector_report.build_report({}, inp, out, figures=False, profile=profile)
    (tmp_path / f"direct-companion-{demand:g}-{attack}-{profile}.pdf").write_bytes(pdf)
    text = " ".join(
        " ".join((page.extract_text() or "").split("\nProject:", 1)[0].split())
        for page in PdfReader(io.BytesIO(pdf)).pages
    )
    provided = out["shear"]["links"]
    resistance = f"{provided['res']['vrd']:.3f}"
    assert f"PL-01 Shear Vy,Ed {demand:.3f} kN" in text
    assert "PL-01 Torsion TEd 40.000 kNm" in text
    if attack == "current":
        assert f"Shear with links PL-01 PASS {100.0 * provided['util']:.1f} %" in text
        if profile != "Brief":
            assert resistance in text
            assert "The links resistance is not assessed" not in text
    else:
        assert "Shear with links PL-01 NOT ASSESSED" in text
        assert resistance not in text
