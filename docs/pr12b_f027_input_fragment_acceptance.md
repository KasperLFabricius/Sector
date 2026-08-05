# PR-12B F-027 active-input fragment acceptance

## Frozen objective

Run ordinary active-pane edits and pane switches inside one sequential Streamlit
fragment. Publish a new canonical engineering draft only after the selected pane
and the complete retained input payload have been reconstructed successfully.

## Fragment and commit boundary

- `_input_workspace` is one non-parallel `st.fragment`; no input stage or material
  family is dispatched concurrently.
- The existing ordered `_input_tab` and conditional `_material_tab` identities are
  unchanged. PR-12A1/A2 still ensure that only the selected pane emits elements.
- Every fragment invocation marks the Inputs build in progress before mounting a
  widget. A normal return from `build_inputs` is the only commit point.
- A successful commit snapshots all retained scalar and canonical table inputs,
  publishes the complete `_latest_inputs` payload, clears the genuine-event
  journal, closes the in-progress marker, and only then services autosave or a
  queued report request.
- A superseded or failed render leaves the in-progress marker and event journal
  intact. The next invocation restores the last completed draft and replays all
  accumulated genuine events before remounting widgets.
- Navigation callbacks continue to snapshot only a completed Inputs build. An
  interrupted partial namespace can never replace the canonical draft.
- Analysis calculation, project hashing, project download, report generation and
  autosave consume the same latest completed payload and retained values.

## Batching semantics

The complete-render commit is the batching boundary. Related browser events may
accumulate in `_pending_input_events` while a previous render is superseded, and
the next successful fragment invocation commits them together. Sector does not add
`st.form` submit gates: many engineering controls enable, constrain or select later
controls in the same pane and must retain immediate dependent feedback.

## Required evidence

- Structural assertions pin the sequential fragment and the exact recovery/build/
  commit/autosave/report order.
- Adversarial AppTest recovery accumulates edits from different panes plus nested
  material navigation, then proves one complete payload and calculation snapshot
  contain every latest value.
- A due autosave triggered by an input edit serializes that same latest value.
- Live-browser evidence distinguishes a fragment-scoped active-pane edit from a
  full workspace rerun and covers rapid outer/nested stage switching.
- The reported sparse fatigue row (spectrum `1`, bin `Train`, 36,000 cycles and
  only `Delta Mx,Ed = 17 kNm`) is accepted with explicit zero defaults for the
  omitted action components, survives pane navigation, and reaches calculation.

## Explicit exclusions

- Opt-in phase telemetry, browser timing distributions, payload/long-task budgets
  and broad performance thresholds remain PR-12C/F-028.
- No parallel fragment, forced form-submit workflow, cache broadening, solver,
  formula, material law, result, provenance, report/manual content, project schema,
  package, workflow, version, release, calculation-trace, PR-13/PR-14 or v0.93
  change.
