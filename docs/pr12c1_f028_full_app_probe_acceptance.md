# PR-12C1 F-028 full-app probe acceptance

## Frozen boundary

This independent slice starts from accepted base
`051d6ad4b096b775d7d3ca9ef44af9ab635f0609`. It owns only the complete
Streamlit full-application envelope. Fragment ownership, phase breakdowns and
warm/dense fragment budgets belong to the subsequent PR-12C2 slice.

The probe opens before `st.set_page_config`, the optional sidebar logo, title,
caption or any other top-level Streamlit output. It closes after the selected
workspace and optional manual dialog have rendered. A fragment-scoped context
cannot open or close a full-app record.

## Opt-in and data boundary

The normal application remains primary. With
`SECTOR_PERFORMANCE_TELEMETRY` absent or false, the probe creates no state,
installs no message wrapper and writes no file. Only `1`, `true`, `yes` and `on`
(case insensitive) enable it. An optional
`SECTOR_PERFORMANCE_TELEMETRY_PATH` appends local JSON-lines evidence; the
application never invents or enables a destination.

Each record contains only:

- schema and monotonically increasing run number;
- the fixed `app` kind, UTC start, total duration and interrupted flag;
- final workspace, input-stage and material-family labels; and
- ForwardMsg count, total protobuf bytes, largest message and accounting flag.

Engineering values, point tables, loads, results, message content, file names,
paths and user identity are excluded. Private state is bounded to 128 records,
detached by the snapshot API and excluded from the project schema.

All diagnostic operations fail inertly. Missing Streamlit internals, fragment
contexts, inaccessible state, protobuf-size failures and an unwritable optional
destination cannot suppress or modify the original Streamlit message or
application execution. A message is counted only after Streamlit's original
enqueue returns successfully, so an interrupt cannot advertise output that did
not reach the browser. A superseded unfinished app record is retained with an
explicit interrupted flag.

## Cold browser budget

Evidence was collected on 2026-08-05 with Python 3.13, Streamlit 1.59.2 and the
real in-app browser. Every sample used a fresh Python process, localhost origin,
telemetry file and autosave directory. The current default project was used;
the browser reached the Sector v0.91 heading with no console warnings or errors.
Percentiles use the nearest-rank method.

Frozen tripwires for this accepted machine/runtime are:

- five cold full-app samples;
- p95 duration no more than 2,500 ms;
- p95 aggregate ForwardMsg size no more than 64 KiB; and
- largest individual ForwardMsg no more than 8 KiB.

Measured durations were 1,516.9331, 1,501.8362, 1,424.1884, 1,863.0469 and
1,668.3758 ms. The p50 was 1,516.9331 ms and p95/maximum was 1,863.0469 ms.
Every cold record contained exactly 116 messages, 41,747 aggregate protobuf
bytes and a 3,390-byte largest message. The invariant message count includes
the page configuration and header/sidebar outputs because the queue wrapper is
installed before their first emission.

## Acceptance closure

- Structural order guards pin the single opener before page configuration,
  logo, title and caption, and the single closer to the final executable line.
- Disabled unit and live-AppTest probes are exactly inert.
- Enabled unit and live-AppTest probes seal aggregate bytes and final labels.
- Fragment contexts cannot affect the full-app owner.
- Reopening retains the superseded owner as interrupted before starting the next
  monotonically numbered run.
- History is bounded and snapshots cannot mutate live state.
- Broken message sizing still forwards the exact original message.
- An interrupted original enqueue propagates unchanged and contributes no
  message or byte count.
- Broken state and local-file destinations do not escape the probe API.
- Probe keys are absent from current project scalar and table inventories.

## Explicit exclusions

- No fragment owner, nested-fragment selector or fragment timing phase.
- No warm/dense fragment budget; those remain PR-12C2.
- No calculation trace, solver, formula, catalogue, standard, citation, verdict
  or mutable engineering cache.
- No UI toggle, remote collection, network export or user tracking.
- No persistence/schema, report/manual content, package/workflow, signing,
  release, application-version, PR-13+, or v0.93 roadmap change.
