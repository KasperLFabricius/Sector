"""0.97.1 S1: stored result presentation (AR-01, UI-01) and Calculate progress (UI-04).

The digest tests compare a stored presentation with a presentation that is
calculated again from the same inputs and results. The expected values come
from that second, independent calculation, not from the stored record.
"""

from __future__ import annotations

import copy
import pathlib
import sys

import pytest
from streamlit.testing.v1 import AppTest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import case_analysis  # noqa: E402
import load_cases  # noqa: E402
import project_io  # noqa: E402
import reproducible_example  # noqa: E402
import result_presentation as rp  # noqa: E402
from app import calculation_service, stored_presentation  # noqa: E402
from app_workflow_navigation import goto_page, goto_widget_owner  # noqa: E402

APP = str(ROOT / "app" / "sector_app.py")
_STAGE = ("sections", "S1", "stages", "final")


def _stage(record):
    value = record
    for key in _STAGE:
        value = value[key]
    return value


@pytest.fixture(scope="module")
def reference():
    """Reference project inputs and one calculation with the progress events."""

    inp = calculation_service.project_inputs(reproducible_example.project_json())
    events = []
    results = calculation_service.run_analysis(
        copy.deepcopy(inp), progress=lambda *event: events.append(event)
    )
    return inp, results, events


@pytest.fixture
def no_active_record():
    stored_presentation.activate(None)
    yield
    stored_presentation.activate(None)


def _counting(monkeypatch):
    calls = []
    original = rp.calculated_multi_case_summary_rows

    def counted(*args, **kwargs):
        calls.append(kwargs.get("stale", False))
        return original(*args, **kwargs)

    monkeypatch.setattr(rp, "calculated_multi_case_summary_rows", counted)
    return calls


# --- AR-01: record, digests and reads -------------------------------------


def test_stored_rows_agree_with_rows_calculated_again(reference, no_active_record):
    inp, results, _events = reference
    before = project_io.result_sha256(results)
    record = rp.stored_presentation_record(inp, results, capacity_contract=("c", "1"))

    recalculated = rp.calculated_multi_case_summary_rows(copy.deepcopy(inp), results)
    assert _stage(record)["rows_sha256"] == project_io.result_sha256(recalculated)
    assert record["result_sha256"] == before
    # The record stays beside the results: the results and their digest do not change.
    assert project_io.result_sha256(results) == before
    assert stored_presentation.SESSION_KEY not in results
    assert record["capacity_contract"] == ["c", "1"]
    assert record["engineering_input_sha256"] == project_io.result_sha256(
        ("sector-engineering-input-v1", inp["signature"])
    )


def test_record_is_keyed_by_section_stage_and_case(reference, no_active_record):
    inp, results, _events = reference
    record = rp.stored_presentation_record(inp, results)
    stage = _stage(record)
    rows = stage["rows"]
    positions = sorted(p for values in stage["cases"].values() for p in values)
    assert positions == list(range(len(rows)))
    for key, values in stage["cases"].items():
        assert {f"{rows[p]['family']}:{rows[p]['case']}" for p in values} == {key}
        assert stored_presentation.case_rows(record, key) == [rows[p] for p in values]
    assert any(key.startswith("plastic:") for key in stage["cases"])
    assert any(key.startswith("elastic:") for key in stage["cases"])
    assert stored_presentation.governing_rows(record) == rp.governing_summary_rows(rows)
    assert stored_presentation.case_rows(record, "plastic:no such case") == []
    assert stored_presentation.case_rows(record, "plastic:PL-1", stage_key="other") == []
    assert stored_presentation.governing_rows({}) == []


def test_active_record_is_read_without_a_new_calculation(
    reference, no_active_record, monkeypatch
):
    inp, results, _events = reference
    record = rp.stored_presentation_record(inp, results)
    calls = _counting(monkeypatch)
    stored_presentation.activate(record)

    first = rp.multi_case_summary_rows(copy.deepcopy(inp), results)
    first[0]["status"] = "CHANGED BY THE CALLER"
    second = rp.multi_case_summary_rows(copy.deepcopy(inp), results)

    assert calls == []
    assert project_io.result_sha256(second) == _stage(record)["rows_sha256"]


def _changed_signature(inp, results):
    return dict(inp, signature=inp["signature"] + ("edited",)), results


def _changed_scalar(inp, results):
    return dict(inp, label_scale=float(inp.get("label_scale") or 1.0) + 0.5), results


def _changed_results(inp, results):
    changed = copy.deepcopy(results)
    changed["edited"] = True
    return inp, changed


def _no_signature(inp, results):
    changed = dict(inp)
    changed.pop("signature")
    return changed, results


@pytest.mark.parametrize(
    "change",
    [_changed_signature, _changed_scalar, _changed_results, _no_signature],
    ids=["signature", "scalar-input", "results", "no-signature"],
)
def test_other_inputs_or_results_do_not_read_the_record(
    reference, no_active_record, monkeypatch, change
):
    inp, results, _events = reference
    record = rp.stored_presentation_record(inp, results)
    other_inp, other_results = change(inp, results)
    assert stored_presentation.read_rows(record, other_inp, other_results) is None

    calls = _counting(monkeypatch)
    stored_presentation.activate(record)
    monkeypatch.setattr(
        stored_presentation, "remember_variant", lambda *args, **kwargs: False
    )
    rows = rp.multi_case_summary_rows(other_inp, other_results)
    assert calls == [False]
    assert isinstance(rows, list)


def test_new_source_revision_does_not_read_the_record(reference, no_active_record, monkeypatch):
    inp, results, _events = reference
    record = rp.stored_presentation_record(inp, results)
    assert stored_presentation.read_rows(record, inp, results) is not None
    monkeypatch.setattr(stored_presentation, "source_revision", lambda: "another-build")
    assert stored_presentation.read_rows(record, inp, results) is None


@pytest.mark.parametrize("damage", ["rows", "digest", "schema", "stage", "type"])
def test_damaged_record_fails_closed(reference, no_active_record, damage):
    inp, results, _events = reference
    record = rp.stored_presentation_record(inp, results)
    if damage == "rows":
        _stage(record)["rows"][0]["status"] = "PASS?"
    elif damage == "digest":
        _stage(record)["rows_sha256"] = "0" * 64
    elif damage == "schema":
        record["schema"] = 2
    elif damage == "stage":
        record["sections"]["S1"]["stages"] = {}
    else:
        _stage(record)["rows"] = tuple(_stage(record)["rows"])
    assert stored_presentation.read_rows(record, inp, results) is None
    assert stored_presentation.read_rows(None, inp, results) is None


def test_stale_presentation_is_calculated_one_time(reference, no_active_record, monkeypatch):
    inp, results, _events = reference
    record = rp.stored_presentation_record(inp, results)
    calls = _counting(monkeypatch)
    stored_presentation.activate(record)

    stale = rp.multi_case_summary_rows(inp, results, stale=True)
    again = rp.multi_case_summary_rows(inp, results, stale=True)
    current = rp.multi_case_summary_rows(inp, results)

    assert calls == [True]
    assert project_io.result_sha256(again) == project_io.result_sha256(stale)
    assert project_io.result_sha256(current) == _stage(record)["rows_sha256"]
    assert any(row["status"] == "STALE" for row in stale)
    assert len(record["variants"]) == 1


def test_variants_are_bounded_and_belong_to_the_calculation(reference, no_active_record):
    inp, results, _events = reference
    record = rp.stored_presentation_record(inp, results)
    rows = _stage(record)["rows"]
    for index in range(stored_presentation.MAX_VARIANTS + 2):
        edited = dict(inp, label_scale=10.0 + index)
        assert stored_presentation.remember_variant(record, edited, results, rows)
    assert len(record["variants"]) == stored_presentation.MAX_VARIANTS
    newest = dict(inp, label_scale=10.0 + stored_presentation.MAX_VARIANTS + 1)
    assert stored_presentation.read_rows(record, newest, results) == rows
    oldest = dict(inp, label_scale=10.0)
    assert stored_presentation.read_rows(record, oldest, results) is None

    other_inp, other_results = _changed_results(inp, results)
    assert not stored_presentation.remember_variant(record, other_inp, other_results, rows)
    assert not stored_presentation.remember_variant(dict(record), *_changed_signature(inp, results), rows)
    assert stored_presentation.new_record({}, results, rows) is None


def test_digest_failures_give_no_record_and_no_stored_rows(
    reference, no_active_record, monkeypatch
):
    inp, results, _events = reference
    record = rp.stored_presentation_record(inp, results)
    rows = _stage(record)["rows"]
    unsupported = object()
    assert stored_presentation.engineering_input_sha256(dict(inp, signature=(unsupported,))) is None
    assert stored_presentation.engineering_input_sha256(None) is None
    assert stored_presentation.input_scalars_sha256(None) is None
    assert stored_presentation.new_record(inp, {"x": unsupported}, rows) is None
    assert stored_presentation.new_record(inp, results, [{"x": unsupported}]) is None
    assert stored_presentation.read_rows(record, inp, {"x": unsupported}) is None

    # A variant request with damaged variant storage gives no stored rows.
    edited = dict(inp, label_scale=99.0)
    for damaged in ({"variants": None}, {"variants": {}}):
        copy_record = dict(record, **damaged)
        assert stored_presentation.read_rows(copy_record, edited, results) is None
    key = f"{stored_presentation.input_scalars_sha256(edited)}:current"
    assert stored_presentation.read_rows(
        dict(record, variants={key: "damaged"}), edited, results
    ) is None
    assert not stored_presentation.remember_variant(
        dict(record, variants=[]), edited, results, rows
    )
    assert not stored_presentation.remember_variant(
        record, edited, results, [{"x": unsupported}]
    )

    # A scalar digest that cannot be calculated also gives no stored rows.
    original = project_io.result_sha256

    def no_scalars(value):
        if isinstance(value, tuple) and value[:1] == ("sector-input-scalars-v1",):
            raise TypeError("unsupported")
        return original(value)

    monkeypatch.setattr(project_io, "result_sha256", no_scalars)
    assert stored_presentation.input_scalars_sha256(inp) is None
    assert stored_presentation.read_rows(record, inp, results) is None


def test_presentation_record_of_the_service(reference, no_active_record):
    inp, results, _events = reference
    events = []
    record = calculation_service.presentation_record(
        inp, results, progress=lambda *event: events.append(event)
    )
    assert events == [(calculation_service.PROGRESS_REGISTER, 1, 1, "")]
    assert stored_presentation.read_rows(record, inp, results) is not None
    assert calculation_service.presentation_record(inp, {}) is None


# --- UI-04: progress callbacks --------------------------------------------


def test_run_case_tables_reports_each_action_set(reference):
    inp, _results, _events = reference
    events = []

    def runner(case_inp, *, reuse_plastic=None):
        return {}

    with_callback = case_analysis.run_case_tables(
        inp, runner, progress=lambda *event: events.append(event)
    )
    without_callback = case_analysis.run_case_tables(inp, runner)

    plastic = list(case_analysis.case_records(inp, "plastic"))
    elastic = list(case_analysis.case_records(inp, "elastic"))
    expected = [
        (case_analysis.PROGRESS_PLASTIC, index, len(plastic), str(record[load_cases.NAME]))
        for index, record in enumerate(plastic, start=1)
    ] + [
        (case_analysis.PROGRESS_ELASTIC, index, len(elastic), str(record[load_cases.NAME]))
        for index, record in enumerate(elastic, start=1)
    ]
    assert events == expected
    assert project_io.result_sha256(with_callback) == project_io.result_sha256(without_callback)


def test_run_analysis_reports_the_steps_and_keeps_the_results(reference):
    inp, results, events = reference
    steps = [event[0] for event in events]
    assert steps[0] == calculation_service.PROGRESS_SECTION
    assert steps[-1] == calculation_service.PROGRESS_SELECTION
    assert calculation_service.PROGRESS_PLASTIC in steps
    assert calculation_service.PROGRESS_ELASTIC in steps
    assert (calculation_service.PROGRESS_FATIGUE in steps) is bool(inp.get("fatigue_on"))
    assert (calculation_service.PROGRESS_SPACING in steps) is bool(inp.get("clear_spacing_on"))
    plain = calculation_service.calculate_project(copy.deepcopy(inp))
    assert plain["result_sha256"] == project_io.result_sha256(results)


def test_single_case_inputs_report_one_analysis_step(reference):
    # Input documents without case tables take the single-analysis path.
    inp = {
        key: value
        for key, value in reference[0].items()
        if key not in {"plastic_cases", "elastic_cases"}
    }
    # The Formula 7.100 NA check needs a reference action set of a case table.
    inp["sls_heightened_on"] = False
    events = []
    result = calculation_service.run_analysis(
        copy.deepcopy(inp), progress=lambda *event: events.append(event)
    )
    steps = [event[0] for event in events]
    assert steps[:2] == [
        calculation_service.PROGRESS_SECTION,
        calculation_service.PROGRESS_SINGLE,
    ]
    assert steps[-1] == calculation_service.PROGRESS_SELECTION
    assert (calculation_service.PROGRESS_FATIGUE in steps) is bool(inp.get("fatigue_on"))
    assert (calculation_service.PROGRESS_SPACING in steps) is bool(inp.get("clear_spacing_on"))
    assert project_io.result_sha256(result) == project_io.result_sha256(
        calculation_service.run_analysis(copy.deepcopy(inp))
    )


def test_calculate_project_passes_the_callback(reference):
    inp, results, events = reference
    received = []
    result_set = calculation_service.calculate_project(
        [copy.deepcopy(inp)], progress=lambda *event: received.append(event)
    )[0]
    assert received == events
    assert result_set["result_sha256"] == project_io.result_sha256(results)


# --- Application: one build for each Calculate ----------------------------


def _app_calculate(at):
    goto_page(at, "Analysis")
    at.button(key="calculate").click().run(timeout=300)
    assert not at.exception, at.exception
    return at


def _assert_stored_matches_recalculation(at):
    state = at.session_state
    record = state[stored_presentation.SESSION_KEY]
    snapshot = state["result_input_snapshot"]
    results = state["results"]
    calculation = state["calculation_record"]
    recalculated = rp.calculated_multi_case_summary_rows(copy.deepcopy(snapshot), results)
    assert _stage(record)["rows_sha256"] == project_io.result_sha256(recalculated)
    assert record["result_sha256"] == calculation["result_sha256"]
    assert record["engineering_input_sha256"] == calculation["engineering_input_sha256"]
    return record


def test_app_stores_the_presentation_and_a_rerun_reads_it(monkeypatch):
    at = AppTest.from_file(APP, default_timeout=300)
    at.session_state["_pending_project"] = reproducible_example.project_json()
    at.run()
    assert not at.exception, at.exception
    _app_calculate(at)

    first = _assert_stored_matches_recalculation(at)
    labels = [status.label for status in at.status]
    assert any(label.startswith("Calculation complete in ") for label in labels), labels

    calls = _counting(monkeypatch)
    at.run()
    assert not at.exception, at.exception
    assert calls == []

    # An engineering input edit: the record is not read for the new inputs.
    # The stale register of the retained calculation is calculated one time.
    old_increment = float(at.session_state["v_inc"])
    goto_widget_owner(at, "v_inc")
    at.number_input(key="v_inc").set_value(old_increment / 2.0).run()
    goto_page(at, "Analysis")
    at.run()
    assert not at.exception, at.exception
    assert calls == [True]

    # A new Calculate stores a new presentation that agrees with a new calculation.
    _app_calculate(at)
    second = _assert_stored_matches_recalculation(at)
    assert second["engineering_input_sha256"] != first["engineering_input_sha256"]


def test_app_progress_shows_a_stopped_calculation(monkeypatch):
    def stopped(inp, **kwargs):
        kwargs["progress"](calculation_service.PROGRESS_SECTION, 1, 1, "")
        raise RuntimeError("solver stopped")

    monkeypatch.setattr(calculation_service, "run_analysis", stopped)
    at = AppTest.from_file(APP, default_timeout=300)
    at.session_state["_pending_project"] = reproducible_example.project_json()
    at.run()
    _app_calculate(at)
    assert [status.label for status in at.status] == ["Calculation stopped"]
    assert at.error
    assert stored_presentation.SESSION_KEY not in at.session_state


def test_app_keeps_the_results_when_the_register_build_fails(monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("register build failed")

    monkeypatch.setattr(calculation_service, "presentation_record", broken)
    at = AppTest.from_file(APP, default_timeout=300)
    at.session_state["_pending_project"] = reproducible_example.project_json()
    at.run()
    _app_calculate(at)
    state = at.session_state
    assert stored_presentation.SESSION_KEY not in state
    assert state["calculation_record"]["result_sha256"] == project_io.result_sha256(
        state["results"]
    )
    # The overview calculates the rows as before 0.97.1; no calculation error.
    assert not [
        item.value for item in at.error
        if str(item.value).startswith("Calculation blocked")
    ]
    assert any(
        "governing" in str(item.value) for item in (*at.error, *at.warning, *at.success)
    )
    labels = [status.label for status in at.status]
    assert any(label.startswith("Calculation complete in ") for label in labels), labels
