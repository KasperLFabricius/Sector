# PR-12A1 F-018 responsive outer-stage acceptance

## Frozen objective

Replace the clipped outer input-tab strip with one full-width stage selector and
mount only its selected outer stage. Preserve the existing complete input payload
and exact retained values while the other four outer stages are unmounted.

## Ordered identity

The selector key remains `_input_tab` and has exactly these ordered values:

1. `1 middle-dot Analysis settings`
2. `2 middle-dot Section`
3. `3 middle-dot Material parameters`
4. `4 middle-dot Loads`
5. `Project & report`

`middle-dot` is the existing runtime `chr(0x00B7)` value, keeping source ASCII.
An absent or unknown selection resolves to the first value.

## Active boundary

- Exactly one outer stage may emit Streamlit elements on an Inputs run.
- Inactive widgets reconstruct values from pending genuine events, then the
  completed durable draft, then a live value, then their declared default.
- Inactive action buttons are false and cannot invoke callbacks.
- Inactive point, load-case, fatigue-spectrum and bridge editors use their current
  canonical base tables and never replay a stale widget seed.
- Raw `st.*` bodies are explicitly fenced by their owning stage. A pending Section
  clear confirmation cannot render or mutate geometry from another stage.
- Project/report fragment values remain live-authoritative while their fragment is
  mounted. Durable values are fallbacks; they do not overwrite a newer fragment
  edit during project serialization or autosave.
- Analysis fragment reruns restore the completed input draft before calculation,
  project hashing or autosave reads hidden input keys.

## Responsive evidence

At 390, 768, 1280 and 1920 CSS pixels the selector remains inside the document,
shows its full selected label, and exposes all five ordered choices without a
horizontal tab scroller.

## Explicit exclusions

- Material-family tabs retain their current mounting behavior; their active-only
  boundary is PR-12A2.
- F-027 fragment/batching boundaries remain PR-12B; telemetry and performance
  budgets remain PR-12C/F-028.
- No solver, formula, result, provenance, report/manual content, project schema,
  package, workflow, version, release, calculation trace, PR-13/PR-14 or v0.93
  change.
