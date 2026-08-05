# PR-12A2 F-026 material-family active-boundary acceptance

## Frozen objective

Replace the material-family tab strip with one full-width selector and mount only
the selected family while reconstructing the complete retained material payload.
This completes the nested active-pane boundary begun by PR-12A1.

## Ordered identity

The selector key remains `_material_tab` and has these ordered values:

1. `Concrete`
2. `Mild steel`
3. `Prestressing steel`
4. `Fatigue details`, present only when fatigue analysis is enabled

An absent or unknown selection resolves to `Concrete`. Disabling fatigue while
`Fatigue details` is selected also resolves to `Concrete`.

## Active boundary and retained payload

- No material family emits Streamlit elements unless the outer Material
  parameters stage is selected.
- Exactly one family emits elements when the Material parameters stage is active.
- Inactive family widgets reconstruct from pending genuine events, then the
  completed durable draft, then live state, then their declared defaults.
- A value widget's first browser mount after being inactive is seeded explicitly
  from that retained value; Streamlit's positional minimum or first option cannot
  replace the engineering draft. Later active reruns return to ordinary live
  widget ownership.
- Leaving Inputs clears only the internal mount-ownership marker, so returning
  from Analysis reseeds every remounted input from the durable draft.
- Inactive add, duplicate, delete and auto actions are false and cannot rerun or
  mutate a catalogue.
- Concrete, mild-steel, prestressing-steel and enabled fatigue catalogues retain
  exact IDs, order, values, assignments and selected entries while unmounted.
- The complete material objects, assignment maps and analysis payload are still
  reconstructed on every completed Inputs run; this is a rendering boundary, not
  a mechanics shortcut.
- The outer `Auto-calc all derived values` action retains its existing one-shot
  behavior, including when Concrete is not the selected family.
- `_material_tab` remains a session preference and does not enter project schema.

## Responsive browser evidence

At 390 and 1920 CSS pixels the full-width selector stays inside the document with
zero horizontal overflow and no material tablist. A fresh browser session mounts
the retained 2005/DK concrete preset with `fck = 35.00`, switches to Mild steel
without Concrete controls, then remounts Concrete with the retained value.

## Explicit exclusions

- No solver, formula, material law, catalogue schema, assignment, result,
  provenance, report/manual, persistence, package, workflow, version, release,
  calculation-trace, PR-13/PR-14 or v0.93 change.
- Fragment/batching boundaries remain PR-12B; telemetry and performance budgets
  remain PR-12C/F-028.
