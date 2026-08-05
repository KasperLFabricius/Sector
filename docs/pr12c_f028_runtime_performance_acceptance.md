# PR-12C F-028 runtime performance acceptance

## Frozen boundary

This slice establishes opt-in, local-only measurements for the accepted
Streamlit rerun architecture on base
`051d6ad4b096b775d7d3ca9ef44af9ab635f0609`. It does not change any solver,
engineering input, result, persistence payload, report, manual, package,
workflow, application version or Product Identity surface.

The ordinary application is the primary contract. With
`SECTOR_PERFORMANCE_TELEMETRY` absent or false, no telemetry state is created,
no message wrapper is installed and no output file is written. The feature is
enabled only by the explicit values `1`, `true`, `yes` or `on` (case
insensitive). An optional `SECTOR_PERFORMANCE_TELEMETRY_PATH` appends local
JSON-lines evidence; it is never inferred or enabled by the application.

## Complete run inventory

Exactly six run owners exist:

- one full-application owner;
- the active Inputs fragment;
- Save / Load;
- Report;
- Quick Section; and
- Analysis.

Nested fragment bodies rendered by an Inputs rerun do not open competing
records. A directly requested nested fragment owns its record. Every normal,
early-return and rerun exit seals the active owner before control leaves it.
Superseded owners are retained as interrupted records instead of being silently
dropped.

Each record contains only:

- schema and monotonically increasing run number;
- app/fragment kind, the friendly owner name and Streamlit fragment ID;
- final workspace, input-stage and material-family labels;
- UTC start and total duration;
- phase count/total/maximum/latest duration;
- ForwardMsg count, total protobuf bytes and largest protobuf message; and
- byte-accounting and interrupted flags.

Engineering values, point tables, loads, results, report content, message
content, file names, paths and user identity are excluded. Runtime state is
private, bounded to 128 records, detached by the snapshot API and excluded from
project persistence.

## Phase inventory

The only advertised phases are `startup`, `pane_construction`,
`normalization`, `input_assembly`, `preview` and `autosave`. Timing wraps the
accepted implementation boundaries; it does not create an alternative
calculation path. Solver timing is deliberately excluded because F-028 measures
UI rerun construction, not engineering mechanics.

Diagnostic failures are inert: unavailable Streamlit internals, protobuf size
errors, state-proxy errors and an unwritable optional JSONL destination cannot
suppress, alter or duplicate the original Streamlit message or engineering
execution.

## Browser fixture and method

Evidence was collected on 2026-08-05 with Python 3.13, Streamlit 1.59.2 and the
real in-app browser against hidden localhost servers. Every cold sample used a
fresh Python process, origin, telemetry file and autosave directory. Warm
samples used one established browser session. Percentiles use the nearest-rank
method; p50 for an even sample is the mean of the two central observations.

The small fixture is the current default project. The deterministic dense
current-schema fixture contains 64 concrete corners, 256 reinforcing bars, 64
tendons, 200 plastic actions, 200 elastic actions and 50 grouped-fatigue bins.
Its project hash was verified by the production loader before measurement.

The in-app browser intentionally does not expose `PerformanceObserver` or the
page Performance timeline to automation. Browser action-to-settle time is
therefore the conservative long-task proxy for this gate. Server run duration
and protobuf delta size are recorded independently by the application. No
browser console warning or error was observed in the small or dense runs.

## Frozen budgets

These are regression tripwires for the accepted machine/runtime, not claims
about every deployment host:

| Scenario | Samples | Duration budget | Forward-message budget |
| --- | ---: | ---: | ---: |
| Cold default full-app run | 5 | p95 <= 750 ms | p95 <= 64 KiB |
| Warm small stage fragment | 10 | p95 <= 400 ms | p95 <= 64 KiB |
| Warm small scalar fragment | 10 | p95 <= 400 ms | p95 <= 32 KiB |
| Warm dense stage fragment after first mount | 10 | p95 <= 750 ms | p95 <= 64 KiB |
| First dense Section mount | 1 | max <= 1,250 ms | max <= 2.50 MiB |
| Small browser action-to-settle proxy | 20 | max <= 2,000 ms | not applicable |

The first dense Section mount is a separate budget because it must publish the
complete live-grid payload once. Treating it as an ordinary warm delta would
hide the distinction between initial component construction and subsequent
fragment updates.

## Exact measured evidence

| Scenario | p50 duration | p95 duration | maximum | p95 bytes | maximum bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Cold default full-app | 436.9913 ms | 487.6524 ms | 487.6524 ms | 41,239 | 41,239 |
| Warm small stage | 169.3858 ms | 224.6927 ms | 224.6927 ms | 40,889 | 40,889 |
| Warm small scalar | 186.3361 ms | 258.3829 ms | 258.3829 ms | 18,569 | 18,569 |
| Warm dense stage after mount | 302.5335 ms | 431.9831 ms | 431.9831 ms | 40,865 | 40,865 |

The first dense Section mount measured 679.7339 ms, 2,168,755 total bytes and
a 545,527-byte largest message. The twenty small browser action-to-settle
samples measured a 1,189 ms maximum for stage changes and 780 ms for scalar
edits, both including the harness quiet window.

The five cold server durations were 401.5939, 436.9913, 472.1164, 413.5885 and
487.6524 ms. Five alternating warm dense stage pairs remained below 432 ms;
the post-mount Section deltas were 11,427 bytes and Analysis-settings deltas
were 40,865 bytes.

## Acceptance and adversarial closure

- Disabled telemetry is exactly inert in unit and live-AppTest probes.
- Every enabled app and fragment record seals final labels, phase timings and
  real ForwardMsg protobuf byte counts.
- All five production fragment owners are structurally inventoried and observed
  independently in the real browser.
- Parent Inputs reruns exclude nested Save / Load and Report records, while
  direct nested-panel events produce the correct single owner.
- Repeated open calls cannot split one owner; a different owner interruption is
  explicit and retained.
- History remains at 128 records and returned snapshots cannot mutate live
  state.
- Missing queues and failures in size accounting, the state proxy or local file
  append do not alter the original application path.
- Runtime keys and environment controls are absent from current-schema project
  serialization.
- The dense fixture is parsed by the production loader and retains its exact
  cardinalities.

## Explicit exclusions

- No calculation trace is restored.
- No solver, formula, catalogue, standards, citation or verdict changes.
- No cache is added around mutable engineering state.
- No UI telemetry toggle, remote collection, network export or user tracking.
- No persistence/schema, report/manual, package/workflow, signing, release,
  version, PR-13+, or v0.93 roadmap change.
