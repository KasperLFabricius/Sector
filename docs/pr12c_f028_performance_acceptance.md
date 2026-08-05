# PR-12C F-028 opt-in performance diagnostics acceptance

## Frozen objective

Add local, explicitly enabled performance diagnostics for the active-pane
Streamlit application and establish repeatable browser budgets. The diagnostics
measure execution and publication cost only. They must not record engineering
values, change a calculation, or become an application usage-analytics channel.

## Activation and retained identity

- Diagnostics are off unless `SECTOR_PERFORMANCE_TELEMETRY=1` (or an equivalent
  accepted true token) is present before the app starts.
- The ordinary launchers continue to set Streamlit's separate
  `browser.gatherUsageStats` option to false.
- When diagnostics are off, no diagnostic session-state key, output file,
  Streamlit element, project field, report field, or manual field is created.
- When enabled, records remain local and contain only: schema version, run number,
  app/fragment kind, fragment IDs, workspace and pane labels, timestamps,
  durations, phase summaries, and forwarded Streamlit message counts/sizes.
- Records contain no project metadata, geometry, material, load, result, verdict,
  report, manual, calculation-trace, file-content, or user identity value.
- Session storage is bounded to the latest 128 completed runs. A JSON-lines file
  is written only when the engineer/developer also supplies the explicit
  `SECTOR_PERFORMANCE_TELEMETRY_PATH` destination.

## Phase and rerun contract

The exact server phases are:

1. `startup`: autosave restore, pending-project application, and retained-state
   preparation before the workspace dispatcher.
2. `pane_construction`: construction of the selected active Inputs pane.
3. `normalization`: shared material/fatigue catalogue normalization and
   material-identity construction performed before selected-pane rendering;
   selected-pane table normalization remains inside `pane_construction`.
4. `input_assembly`: construction of the complete immutable solver/report input
   payload after the active pane is valid.
5. `preview`: visible section or selected-material preview construction and
   publication; inactive previews publish no phase event.
6. `autosave`: due-check and any atomic autosave serialization/write.

Each full application run and fragment run receives one monotonically increasing
run number. A superseded run is retained as interrupted when the next run begins.
Workspace, input-stage, and material-family labels are sealed at finalization,
after cold-start defaults and queued navigation changes have been applied.
The enabled collector wraps only the current Streamlit script context's forward
queue and records the count, total protobuf bytes, and largest forwarded message
for that run. It does not alter, suppress, reorder, cache, or deserialize a
message. Missing or changed Streamlit internals disable byte accounting safely
without changing application behavior.

## Browser scenarios and measurement rule

Two current-schema projects are used:

- `small`: Sector's default four-corner section, eight reinforcing bars, no
  tendons, and the default single plastic and elastic action rows.
- `dense`: a deterministic valid 64-corner concrete outline, 256 reinforcing
  bars, 64 tendons, 200 plastic action rows, 200 elastic action rows, and 50
  grouped fatigue bins. Material IDs and fatigue assignments remain valid.

Cold samples use a new Streamlit server and browser session. Warm samples reuse
the loaded session. Time-to-idle starts at event dispatch and ends after the
running indicator is absent and no relevant app-root mutation occurs for 250 ms.
Each distribution publishes p50, p95, and maximum. Cold paths use five samples;
warm paths use ten. Long tasks are browser PerformanceObserver entries of at
least 50 ms. Server message bytes are correlated by the diagnostic run number.

## Frozen budgets

The numerical limits below were frozen after the owning PR's five-sample cold
and ten-sample warm browser matrix was complete.  In particular, cold readiness
includes the one-time Python/Streamlit import and websocket path that occurs
before Sector's first instrumented application phase; it is intentionally not
represented as server phase time.  The first warm visit to a pane is retained in
the distributions so a heavy data editor cannot be hidden behind a warm-up.

| Scenario | Project | p50 | p95 | Maximum |
|---|---|---:|---:|---:|
| Cold first usable Inputs | small | 12.0 s | 20.0 s | 24.0 s |
| Cold first usable Inputs | dense | 12.0 s | 15.0 s | 18.0 s |
| Warm outer-pane switch | small | 1.5 s | 2.5 s | 4.0 s |
| Warm outer-pane switch | dense | 3.5 s | 5.0 s | 6.0 s |
| Warm scalar edit | small | 1.0 s | 1.75 s | 3.0 s |
| Warm scalar edit | dense | 2.0 s | 3.5 s | 5.0 s |

Forwarded-message budgets per completed warm action are:

| Action | Project | p95 bytes | Maximum bytes | Completed reruns |
|---|---|---:|---:|---:|
| Outer-pane switch | small | 1.5 MiB | 2.5 MiB | 1 |
| Outer-pane switch | dense | 4.0 MiB | 6.0 MiB | 1 |
| Scalar edit | small | 512 KiB | 1.0 MiB | 1 |
| Scalar edit | dense | 2.0 MiB | 3.0 MiB | 1 |

For every warm action, there is exactly one owning fragment run, zero full-app
runs, and zero extra completed runs after the quiet window. A cold sample may
have at most eight long tasks and 1.5 s total long-task duration for `small`, or
2.5 s for `dense`. A small outer-pane switch may have at most five long tasks and
1.5 s total duration; a dense outer-pane switch may have at most fourteen and
4.5 s. A scalar edit may have at most five long tasks and 1.0 s total duration.

The rapid-switch oracle dispatches 20 alternating outer-stage changes while also
changing one scalar before and one scalar after the burst. It permits interrupted
fragment runs but no full-app run, hang, or post-idle rerun. The final selected
stage and both scalar values must be present in the canonical draft, the next
calculation input snapshot, and a due autosave. Inactive stages emit no widget or
chart payload.

## Exact-head browser evidence

The final local matrix used Python 3.13.0, Streamlit 1.59.2 and headless Chrome
150.0.7871.189.  Each cold sample used a new sequential Streamlit server, isolated
autosave/telemetry directory, new browser context and the numeric loopback address.
Warm samples reused one loaded browser session and required a 250 ms mutation-quiet
window after Streamlit's running indicator disappeared.

| Scenario | Project | Samples | p50 | p95 | Maximum |
|---|---|---:|---:|---:|---:|
| Cold first usable Inputs | small | 5 | 10.763 s | 18.284 s | 18.342 s |
| Cold first usable Inputs | dense | 5 | 10.203 s | 10.514 s | 10.532 s |
| Warm outer-pane switch | small | 10 | 0.994 s | 1.745 s | 2.286 s |
| Warm outer-pane switch | dense | 10 | 2.730 s | 4.460 s | 4.472 s |
| Warm scalar edit | small | 10 | 1.287 s | 1.297 s | 1.301 s |
| Warm scalar edit | dense | 10 | 1.282 s | 1.295 s | 1.302 s |

Cold server records were one full-app run per session.  The instrumented Sector
run itself was 0.319--0.580 s for `small` and 0.535--0.687 s for `dense`; the
remaining cold interval is the intentionally retained pre-phase import, browser
and websocket path.  Cold long-task maxima were eight tasks/0.621 s (`small`) and
five tasks/0.322 s (`dense`).

The first warm outer visit was included.  Small outer payload p95/max were
1,126,999/2,015,634 bytes; dense outer payload p95/max were
1,218,062/2,181,224 bytes.  Scalar payload p95/max were 40,883/40,883 bytes
(`small`) and 40,859/40,859 bytes (`dense`).  Every measured warm action produced
exactly one owning fragment run and no full-app run.  Scalar edits produced no
long task.  Dense outer construction established the retained worst case of
thirteen tasks and less than 4.5 s total long-task duration; no browser console or
page error was observed.

The rapid-switch run dispatched twenty exact alternating stage identities with no
harness retry.  Streamlit coalesced a superseded client event without a full-app
run; after idle the final stage was `1 · Analysis settings`, and the before/after
scalar edits (`v_min=4.0`, `v_max=358.0`) were retained in both the visible widgets
and the downloaded current-schema project.  The accepted interrupted-fragment and
due-autosave tests independently pin the same canonical draft/calculation/save
closure.

## Required focused evidence

- Pure collector tests cover disabled behavior, true-token parsing, bounded run
  identity, interrupted-run closure, exact phase accumulation, exact forwarded
  protobuf byte/count accounting, JSON-lines opt-in, and safe internal-hook
  degradation.
- App structural and adversarial tests pin all six phase boundaries, distinguish
  full and fragment runs, and prove diagnostics never enter project/result/report
  payloads or alter latest-state calculation/autosave behavior.
- Real-browser evidence publishes the two project matrices, rerun/delta metrics,
  long-task counts, rapid-switch closure, and zero browser errors.

## Explicit exclusions

No solver, formula, material law, result, verdict, standards, provenance,
calculation trace, project schema, report/manual content, package, workflow,
version, release, signing, PR-13, PR-14, or v0.93 change. No broad cache is added;
existing immutable figure reuse is unchanged. Performance diagnostics are not
shown in the ordinary UI and are never transmitted remotely.
