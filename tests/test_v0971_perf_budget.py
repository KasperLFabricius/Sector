"""0.97.1 S1: performance budget job (AR-15)."""

from __future__ import annotations

import copy
import json
import math
import pathlib
import re
import tomllib

import pytest
import yaml

from tools import perf_budget
from tools import verify_coverage_gate
from tools import verify_dependency_audit

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "qa.yml"
BASELINE = ROOT / "tools" / "perf_budget_baseline.json"


def _record(ratios, calibration=1.0):
    return {
        "schema": perf_budget.SCHEMA,
        "ratios": dict(ratios),
        "seconds": {
            "calibration": calibration,
            **{phase: value * calibration for phase, value in ratios.items()},
        },
    }


def _ratios(value=1.0):
    return {phase: value for phase in perf_budget.BUDGET_PHASES}


def test_baseline_file_has_a_valid_ratio_for_each_phase():
    baseline = json.loads(BASELINE.read_text(encoding="ascii"))
    assert baseline["schema"] == perf_budget.SCHEMA
    assert set(baseline["ratios"]) == set(perf_budget.BUDGET_PHASES)
    assert all(
        math.isfinite(value) and value > 0.0 for value in baseline["ratios"].values()
    )


@pytest.mark.parametrize(
    ("factor", "state"),
    [(1.0, "ok"), (1.25, "ok"), (1.26, "warn"), (2.0, "warn"), (2.01, "fail"), (0.5, "ok")],
)
def test_compare_states_follow_the_limits(factor, state):
    measured = _record(_ratios(3.0 * factor))
    rows = perf_budget.compare(measured, _record(_ratios(3.0)))
    assert [row["state"] for row in rows] == [state] * len(perf_budget.BUDGET_PHASES)
    assert [row["phase"] for row in rows] == list(perf_budget.BUDGET_PHASES)


def test_compare_rejects_another_schema_and_invalid_ratios():
    baseline = _record(_ratios())
    with pytest.raises(ValueError, match="schema"):
        perf_budget.compare(_record(_ratios()), dict(baseline, schema=99))
    for bad in (0.0, -1.0, math.nan, math.inf):
        broken = copy.deepcopy(baseline)
        broken["ratios"]["calculate"] = bad
        with pytest.raises(ValueError, match="calculate"):
            perf_budget.compare(_record(_ratios()), broken)


def _run_main(monkeypatch, tmp_path, measured, baseline):
    monkeypatch.setattr(perf_budget, "measure", lambda: measured)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="ascii")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    code = perf_budget.main(
        ["--output", str(tmp_path / "out"), "--baseline", str(baseline_path)]
    )
    written = json.loads((tmp_path / "out" / "perf_budget.json").read_text(encoding="ascii"))
    return code, written, summary.read_text(encoding="utf-8")


def test_main_warns_but_passes_inside_the_failure_limit(monkeypatch, tmp_path, capsys):
    ratios = _ratios(1.0)
    ratios["calculate"] = 1.5
    code, written, summary = _run_main(
        monkeypatch, tmp_path, _record(ratios, 2.0), _record(_ratios(1.0))
    )
    out = capsys.readouterr().out
    assert code == 0
    assert written["ratios"]["calculate"] == 1.5
    assert "| calculate |" in summary and "| warn |" in summary
    assert "::warning title=Performance budget::calculate takes 1.50 times" in out
    assert "::error" not in out


def test_main_fails_above_the_failure_limit(monkeypatch, tmp_path, capsys):
    ratios = _ratios(1.0)
    ratios["register_read"] = 2.5
    code, _written, summary = _run_main(
        monkeypatch, tmp_path, _record(ratios), _record(_ratios(1.0))
    )
    assert code == 1
    assert "| fail |" in summary
    assert "::error title=Performance budget::register_read" in capsys.readouterr().out


def test_main_writes_a_baseline(monkeypatch, tmp_path):
    measured = _record(_ratios(2.0))
    measured.update(measured_at_utc="2026-11-13T00:00:00+00:00", platform="x", python="3.14")
    monkeypatch.setattr(perf_budget, "measure", lambda: measured)
    target = tmp_path / "baseline.json"
    assert perf_budget.main(
        ["--output", str(tmp_path / "out"), "--write-baseline", str(target)]
    ) == 0
    baseline = json.loads(target.read_text(encoding="ascii"))
    assert baseline["ratios"] == measured["ratios"]
    assert perf_budget.compare(measured, baseline)[0]["state"] == "ok"


def test_baseline_from_ci_evidence_takes_the_median(tmp_path, capsys):
    paths = []
    for index, value in enumerate((1.0, 3.0, 2.0, 10.0)):
        path = tmp_path / f"run{index}.json"
        path.write_text(json.dumps(_record(_ratios(value))), encoding="ascii")
        paths.append(str(path))
    target = tmp_path / "baseline.json"
    assert perf_budget.main(
        ["--write-baseline", str(target), "--from-evidence", *paths[:3]]
    ) == 0
    assert json.loads(target.read_text(encoding="ascii"))["ratios"] == _ratios(2.0)
    assert perf_budget.main(["--write-baseline", str(target), "--from-evidence", *paths]) == 0
    baseline = json.loads(target.read_text(encoding="ascii"))
    assert baseline["ratios"] == _ratios(2.5)
    assert baseline["source"]["samples"] == 4
    with pytest.raises(ValueError, match="schema"):
        perf_budget.baseline_from_evidence([dict(_record(_ratios()), schema=0)])
    with pytest.raises(SystemExit):
        perf_budget.main(["--baseline", str(target), "--from-evidence", paths[0]])
    with pytest.raises(SystemExit):
        perf_budget.main(["--baseline", str(target)])
    capsys.readouterr()


def test_calibration_workload_is_deterministic():
    first = perf_budget.calibration_workload()
    assert math.isfinite(first)
    assert perf_budget.calibration_workload() == first


def _jobs():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def test_workflow_perf_job_is_pinned_with_limits_and_sha_actions():
    job = _jobs()["perf"]
    assert job == verify_coverage_gate.expected_perf_job()
    assert job["timeout-minutes"] == 30
    run_step = next(step for step in job["steps"] if step["name"] == "Run performance budget")
    assert run_step["timeout-minutes"] == 20
    for step in job["steps"]:
        if "uses" in step:
            assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", step["uses"]), step["uses"]
    # The same cached locked environment steps as the core shards.
    core_steps = _jobs()["core"]["steps"]
    assert job["steps"][:7] == core_steps[:7]


def _workflow_text(mutate):
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    mutate(workflow["jobs"])
    return yaml.safe_dump(workflow, sort_keys=False)


def _drop_perf(jobs):
    jobs.pop("perf")


def _weaken_install(jobs):
    for step in jobs["perf"]["steps"]:
        if step["name"] == verify_dependency_audit.INSTALL_STEP:
            step["run"] = "python -m pip install -r requirements-dev.txt"


def _skip_install(jobs):
    for step in jobs["perf"]["steps"]:
        if step["name"] == verify_dependency_audit.INSTALL_STEP:
            step["if"] = "false"


def _restore_without_failure(jobs):
    for step in jobs["perf"]["steps"]:
        if step["name"] == verify_dependency_audit.RESTORE_STEP:
            step["with"]["fail-on-cache-miss"] = False


def _install_before_preflight(jobs):
    steps = jobs["perf"]["steps"]
    install = next(s for s in steps if s["name"] == verify_dependency_audit.INSTALL_STEP)
    steps.remove(install)
    steps.insert(0, install)


def _masked_preflight(jobs):
    for step in jobs["perf"]["steps"]:
        if step["name"] == verify_dependency_audit.PREFLIGHT_STEP:
            step["continue-on-error"] = True


@pytest.mark.parametrize(
    "mutate",
    [_drop_perf, _weaken_install, _skip_install, _restore_without_failure,
     _install_before_preflight, _masked_preflight],
)
def test_dependency_audit_rejects_a_weakened_perf_job(mutate):
    verify_dependency_audit.validate_workflow(WORKFLOW.read_text(encoding="utf-8"))
    with pytest.raises(verify_dependency_audit.DependencyAuditError, match="performance budget"):
        verify_dependency_audit.validate_workflow(_workflow_text(mutate))


@pytest.mark.parametrize("mutate", [_drop_perf, _weaken_install])
def test_coverage_gate_rejects_a_changed_perf_job(mutate):
    contract = tomllib.loads(
        (ROOT / "quality-coverage-gate.toml").read_text(encoding="utf-8")
    )
    verify_coverage_gate.validate_workflow(contract, WORKFLOW.read_text(encoding="utf-8"))
    with pytest.raises(verify_coverage_gate.CoverageGateContractError, match="performance budget"):
        verify_coverage_gate.validate_workflow(contract, _workflow_text(mutate))
