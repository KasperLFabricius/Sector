"""Performance budget of Sector (AR-15).

The job calculates the reference project through the calculation service,
builds the stored result register, reads it again and builds the Brief,
Standard and Audit reports (without figures, so that the image exporter does
not add its start time). It writes the times to ``<output>/perf_budget.json``
and compares them with the baseline file.

Runner variance. A hosted runner can be faster or slower than the runner of
the baseline. Each phase time is therefore divided by the time of a fixed
calibration workload (pure Python and NumPy, no Sector code) that runs in the
same job. The budget compares these ratios. Each phase takes the minimum of
its repeats, which removes most single delays.

Limits (ratio to the baseline ratio):

* above ``WARN_FACTOR`` (1.25): a warning annotation and a line in the job
  summary; the job passes.
* above ``FAIL_FACTOR`` (2.0): the job fails. This limit is far outside the
  measured runner variance, and it finds a regression of the size that
  AR-01 removed (the result register calculated again on each rerun).

Usage::

    python tools/perf_budget.py --output perf-budget --baseline tools/perf_budget_baseline.json
    python tools/perf_budget.py --output perf-budget --write-baseline tools/perf_budget_baseline.json
"""

from __future__ import annotations

import argparse
import copy
import datetime
import json
import logging
import math
import os
import pathlib
import platform
import sys
import tempfile
import time
from collections.abc import Callable, Mapping

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = 1
WARN_FACTOR = 1.25
FAIL_FACTOR = 2.0
# Phases with a budget, in the order of the run. The calibration and the
# one-time kernel warm-up are recorded without a budget.
BUDGET_PHASES = (
    "input_build",
    "calculate",
    "register_build",
    "register_read",
    "report_brief",
    "report_standard",
    "report_audit",
)
_REPEATS = {"calibration": 3, "calculate": 2, "register_read": 3}
_REPORT_PROFILES = {
    "report_brief": "Brief",
    "report_standard": "Standard",
    "report_audit": "Audit",
}
_REPORT_META = {
    "proj_no": "PERF-BUDGET",
    "proj_name": "Performance budget",
    "section": "Reference section",
    "author": "Sector QA",
    "calculation_state": "CURRENT - performance budget",
}


def calibration_workload() -> float:
    """A fixed CPU workload without Sector code; returns a check value."""

    import numpy as np

    total = 0.0
    for index in range(3_000_000):
        total += math.sqrt(index) * 1.0e-6
    values = {f"k{index}": index for index in range(300_000)}
    total += sum(len(key) for key in values) * 1.0e-6
    rng = np.random.default_rng(1234)
    matrix = rng.standard_normal((160, 160))
    for _ in range(400):
        matrix = np.tanh(matrix @ matrix.T / 160.0)
    return total + float(matrix.sum())


def _timed(function: Callable[[], object], repeats: int = 1) -> tuple[float, object]:
    best = math.inf
    value = None
    for _ in range(max(1, repeats)):
        start = time.perf_counter()
        value = function()
        best = min(best, time.perf_counter() - start)
    return best, value


def measure() -> dict:
    """Run the phases and return the measured record."""

    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "app"))
    os.environ.setdefault(
        "SECTOR_AUTOSAVE_DIR",
        str(pathlib.Path(tempfile.mkdtemp(prefix="sector-perf-")) / "autosave"),
    )
    previous_disable = logging.root.manager.disable
    logging.disable(logging.WARNING)
    try:
        import reproducible_example
        import result_presentation
        import sector_report
        from app import calculation_service, stored_presentation
        from sector import __version__

        seconds: dict[str, float] = {}
        seconds["calibration"], _ = _timed(calibration_workload, _REPEATS["calibration"])
        seconds["input_build"], inp = _timed(
            lambda: calculation_service.project_inputs(reproducible_example.project_json())
        )
        seconds["warm_up"], _ = _timed(calculation_service._warm_solver)
        seconds["calculate"], results = _timed(
            lambda: calculation_service.run_analysis(copy.deepcopy(inp)),
            _REPEATS["calculate"],
        )
        seconds["register_build"], record = _timed(
            lambda: calculation_service.presentation_record(inp, results)
        )
        if record is None:
            raise RuntimeError("the reference project gave no stored result register")
        stored_presentation.activate(record)
        try:
            seconds["register_read"], _ = _timed(
                lambda: result_presentation.multi_case_summary_rows(inp, results),
                _REPEATS["register_read"],
            )
        finally:
            stored_presentation.activate(None)
        for phase, profile in _REPORT_PROFILES.items():
            seconds[phase], pdf = _timed(
                lambda profile=profile: sector_report.build_report(
                    dict(_REPORT_META), inp, results,
                    version=__version__, figures=False, profile=profile,
                )
            )
            if not isinstance(pdf, bytes) or not pdf.startswith(b"%PDF"):
                raise RuntimeError(f"the {profile} report gave no PDF")
    finally:
        logging.disable(previous_disable)
    calibration = seconds["calibration"]
    return {
        "schema": SCHEMA,
        "measured_at_utc": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor(),
        "seconds": {key: round(value, 4) for key, value in seconds.items()},
        "ratios": {
            phase: round(seconds[phase] / calibration, 4) for phase in BUDGET_PHASES
        },
    }


def compare(measured: Mapping, baseline: Mapping) -> list[dict]:
    """Return one finding for each budget phase: ratio factor and state."""

    if baseline.get("schema") != SCHEMA:
        raise ValueError("the performance baseline has another schema")
    rows = []
    for phase in BUDGET_PHASES:
        base = float(baseline["ratios"][phase])
        now = float(measured["ratios"][phase])
        if not (math.isfinite(base) and base > 0.0 and math.isfinite(now)):
            raise ValueError(f"the performance ratio of {phase} is not valid")
        factor = now / base
        state = "fail" if factor > FAIL_FACTOR else "warn" if factor > WARN_FACTOR else "ok"
        rows.append({
            "phase": phase,
            "seconds": float(measured["seconds"][phase]),
            "ratio": now,
            "baseline_ratio": base,
            "factor": round(factor, 3),
            "state": state,
        })
    return rows


def summary_lines(measured: Mapping, rows: list[dict]) -> list[str]:
    lines = [
        "### Performance budget",
        "",
        f"Calibration workload: {measured['seconds']['calibration']:.3f} s. "
        f"Warning above {WARN_FACTOR:.2f} times the baseline ratio, failure above "
        f"{FAIL_FACTOR:.2f} times.",
        "",
        "| Phase | Time (s) | Ratio | Baseline ratio | Factor | State |",
        "|---|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {row['phase']} | {row['seconds']:.2f} | {row['ratio']:.2f} | "
        f"{row['baseline_ratio']:.2f} | {row['factor']:.2f} | {row['state']} |"
        for row in rows
    )
    return lines


def baseline_from_evidence(records: list[Mapping]) -> dict:
    """Return a baseline with the median ratio of each phase of several runs."""

    if not records or any(record.get("schema") != SCHEMA for record in records):
        raise ValueError("the evidence must be performance records of this schema")
    ratios = {}
    for phase in BUDGET_PHASES:
        values = sorted(float(record["ratios"][phase]) for record in records)
        middle = len(values) // 2
        ratios[phase] = round(
            values[middle] if len(values) % 2 else 0.5 * (values[middle - 1] + values[middle]),
            4,
        )
    return {
        "schema": SCHEMA,
        "ratios": ratios,
        "source": {
            "samples": len(records),
            "measured_at_utc": [record.get("measured_at_utc") for record in records],
            "platform": sorted({str(record.get("platform")) for record in records}),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=pathlib.Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--baseline", type=pathlib.Path)
    group.add_argument("--write-baseline", type=pathlib.Path)
    parser.add_argument(
        "--from-evidence", type=pathlib.Path, nargs="+",
        help="with --write-baseline: perf_budget.json files of CI runs (median)",
    )
    args = parser.parse_args(argv)

    if args.from_evidence:
        if args.write_baseline is None:
            parser.error("--from-evidence needs --write-baseline")
        records = [
            json.loads(path.read_text(encoding="ascii")) for path in args.from_evidence
        ]
        args.write_baseline.write_text(
            json.dumps(baseline_from_evidence(records), indent=1, sort_keys=True) + "\n",
            encoding="ascii",
        )
        print(f"Baseline written from {len(records)} records: {args.write_baseline}")
        return 0
    if args.output is None:
        parser.error("--output is necessary for a measurement")

    measured = measure()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "perf_budget.json").write_text(
        json.dumps(measured, indent=1, sort_keys=True) + "\n", encoding="ascii"
    )
    if args.write_baseline is not None:
        baseline = {key: measured[key] for key in ("schema", "ratios")}
        baseline["source"] = {
            key: measured[key] for key in ("measured_at_utc", "platform", "python", "seconds")
        }
        args.write_baseline.write_text(
            json.dumps(baseline, indent=1, sort_keys=True) + "\n", encoding="ascii"
        )
        print(f"Baseline written: {args.write_baseline}")
        return 0

    baseline = json.loads(args.baseline.read_text(encoding="ascii"))
    rows = compare(measured, baseline)
    lines = summary_lines(measured, rows)
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    for row in rows:
        if row["state"] != "ok":
            level = "error" if row["state"] == "fail" else "warning"
            print(
                f"::{level} title=Performance budget::{row['phase']} takes "
                f"{row['factor']:.2f} times its baseline ratio "
                f"({row['seconds']:.2f} s)."
            )
    return 1 if any(row["state"] == "fail" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
