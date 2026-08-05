# PR-12C2 F-028 fragment performance acceptance

## Frozen boundary

This independent slice starts from accepted base
`3d997cea4058f5b0b916e75e88bbc18a235be29a`. It completes the opt-in
performance probe begun by PR-12C1. The application version remains `0.91`.

The existing full-application envelope is retained. This slice adds exact root
ownership for the five current Streamlit fragments:

- `inputs`;
- `save_load`;
- `report`;
- `quick_section`; and
- `analysis`.

It also adds six UI-construction phases: `startup`, `pane_construction`,
`normalization`, `input_assembly`, `preview` and `autosave`. These names are a
closed inventory. No solver, calculation, report/manual content, project schema,
engineering cache or calculation trace is added.

## Root-fragment ownership

Streamlit 1.59.2 may dispatch a queue containing both a parent fragment and a
nested child. During the parent root, the child body executes under its own
fragment ID. Recording that body as a root would split one rerun between two
owners.

The probe therefore uses the actual `ScriptRunContext` reset identity. The
context receives a new `parallel_coordinator` object for every Streamlit run:

- the same reset identity plus a different executing fragment is nested work and
  cannot open or close an owner;
- the same reset identity plus the current owner reuses that owner;
- after the parent root closes, a separately dispatched queued child may open its
  own record under the same reset identity; and
- a new reset identity seals any unfinished preceding owner as interrupted before
  opening the new root.

The fallback identity is the concrete `fragment_ids_this_run` object. Unknown,
unselected and non-fragment contexts are inert. Message accounting retains the
accepted PR-12C1 rule: the original Streamlit enqueue must return successfully
before the message is counted.

## Opt-in and data boundary

`SECTOR_PERFORMANCE_TELEMETRY` remains the only enable switch. Disabled runs
create no probe state, install no wrapper and write no file. The optional
`SECTOR_PERFORMANCE_TELEMETRY_PATH` remains local and explicit.

Schema 2 adds only:

- `fragment_name` and the concrete Streamlit `fragment_id` on fragment records;
  and
- per-phase count, total, maximum and latest milliseconds.

The reset token and phase start timestamps are private live state and are removed
before history, snapshots or JSON-lines output. Engineering values, point tables,
loads, results, message contents, file names, paths and user identity remain
excluded. Project scalar/table inventories still exclude every probe key.

## Browser fixtures and method

Evidence was collected on 2026-08-05 with Python 3.13, Streamlit 1.59.2 and the
real in-app browser. Every server used a fresh localhost port, telemetry file and
autosave directory. Percentiles use the nearest-rank method.

The default project established all five fragment owners. The dense fixture was
generated independently through the current schema and parsed again before use:

- 64 ordered concrete corners;
- 256 reinforcing bars;
- 64 tendons;
- 200 Plastic cases;
- 200 Elastic cases; and
- 50 fatigue bins.

The browser reached visible current-pane content after every measured action.
No application exception or server warning occurred. The browser automation
surface does not expose `PerformanceObserver`/Long Task entries. Sector therefore
does not ship client instrumentation merely to benchmark itself and does not claim
that zero browser long tasks occurred. The non-invasive blocking tripwire is the
measured interaction-to-visible-pane duration, supported by exact server phases
and ForwardMsg sizes.

## Measured default-project runs

Five warm Section label edits produced server durations of 333.6842, 175.1852,
182.4708, 186.0390 and 228.8287 ms:

- p50 186.0390 ms; p95/maximum 333.6842 ms;
- p50 aggregate ForwardMsg size 18,431 bytes; p95/maximum 18,563 bytes;
- maximum individual ForwardMsg 10,748 bytes;
- maximum pane construction 229.7498 ms; and
- maximum visible preview phase 23.7510 ms.

The first Section mount legitimately transferred the complete Plotly figure:
578.6127 ms, 2,015,634 aggregate bytes and a 501,024-byte largest message. A
subsequent warm edit transferred 18,459 bytes, proving that the existing figure
identity and Streamlit delta path avoid repeated full-figure payloads.

The other exact root owners measured:

- `save_load`: 59.4024 ms and 1,682 bytes;
- `report`: 7.4042 ms and 2,701 bytes;
- `analysis`: 11.2224 ms and 4,760 bytes; and
- `quick_section`: 69.6209 ms and 20,159 bytes.

The coalesced input-to-Quick-Section transition retained its superseded input
owner as explicitly interrupted, then recorded the full-app transition and
independent Quick Section root. It did not advertise the nested body as a second
simultaneous owner.

## Measured dense runs

The first dense Section mount was 591.2177 ms server-side and 1,570 ms from the
browser selection to visible dense cardinality. It transferred 2,181,286 bytes;
the largest message was 551,471 bytes and the preview phase was 298.2421 ms.

Five dense warm label edits produced:

- durations 363.9217, 345.0380, 300.0742, 319.4441 and 325.4827 ms;
- p50 325.4827 ms; p95/maximum 363.9217 ms;
- p50 aggregate ForwardMsg size 117,145 bytes; p95/maximum 117,167 bytes;
- maximum individual ForwardMsg 105,836 bytes;
- maximum pane construction 346.6161 ms; and
- maximum preview phase 60.8045 ms.

Five cached dense Section mounts produced server durations of 314.2563,
292.6880, 284.1547, 268.6210 and 241.9634 ms:

- p50 284.1547 ms; p95/maximum 314.2563 ms;
- every aggregate delta was 11,405 bytes;
- maximum individual message 1,632 bytes; and
- browser interaction-to-visible durations 624, 565, 388, 1,439 and 454 ms
  (p50 565 ms; p95/maximum 1,439 ms).

The dense 200-plus-200-case Loads pane mounted in 268.7314 ms with a 52,608-byte
aggregate delta and 27,834-byte largest message.

## Frozen tripwires

For this accepted machine/runtime:

- default warm fragment p95 duration no more than 500 ms and aggregate delta no
  more than 32 KiB;
- dense warm edit and cached-mount p95 duration no more than 500 ms;
- dense warm edit aggregate delta no more than 128 KiB;
- dense cached-mount aggregate delta no more than 16 KiB;
- first dense Section mount no more than 1,000 ms server-side and 3 MiB aggregate;
- dense interaction-to-visible-pane p95 no more than 2,000 ms; and
- no normal completed owner may be relabelled interrupted or split between
  parent and nested fragment identities.

The PR-12C1 cold full-app tripwires remain unchanged.

## Acceptance closure

- Unit adversaries cover coalesced parent/nested queues, later child roots, new-
  run interruption, excluded fragment IDs and phase tokens crossing run numbers.
- Structural guards pin the exact five owners, the six phase labels, startup order
  and measured autosave path.
- Enabled and disabled live AppTest runs retain complete full-app closure.
- Phase values accumulate deterministically and snapshots cannot retain private
  reset identities or phase timestamps.
- Focused probe tests, directly affected fragment/autosave/preview tests, compile,
  diff and unchanged-baseline static-analysis checks are green.
- Default and dense real-browser records are complete, byte-accounted and locally
  preserved under fresh output directories.

## Explicit exclusions

- No remote telemetry, user-facing telemetry toggle, network export, user
  tracking or persistent engineering data.
- No client Long Task collector or claim unsupported by the available browser
  instrumentation.
- No solver, formula, material law, standard, citation, result, verdict,
  calculation trace, project schema, report/manual, package/workflow, signing,
  release, application-version, PR-13/PR-14 or v0.93 roadmap change.
