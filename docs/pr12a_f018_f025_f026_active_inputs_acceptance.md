# PR-12A F-018/F-025/F-026 responsive active-input acceptance

## Frozen objective

Replace the clipped outer input-tab strip with one discoverable full-width stage
selector and mount only the selected input pane. Preserve one complete canonical
draft so changing stage, workspace page or auxiliary view cannot discard an edit
from an unmounted pane.

## Input identity and order

The outer selector has exactly five string values in this order:

1. `1 middle-dot Analysis settings`
2. `2 middle-dot Section`
3. `3 middle-dot Material parameters`
4. `4 middle-dot Loads`
5. `Project & report`

`middle-dot` denotes the existing runtime `chr(0x00B7)` character; the source
remains ASCII. The stored selection key remains `_input_tab` and defaults to the
first value. Unknown stored values are replaced by that default.

The Material parameters pane has exactly these ordered families:

1. `Concrete`
2. `Mild steel`
3. `Prestressing steel`
4. `Fatigue details`, only while fatigue is enabled

The stored material selection key remains `_material_tab`. An unavailable stored
value is replaced by `Concrete`.

## Mount and value contract

- Exactly one outer pane delegates Streamlit output on every Inputs run.
- When Material parameters is active, exactly one material-family pane delegates
  Streamlit output.
- Inactive containers do not emit widgets, editors, expanders, tables, previews,
  plots, uploads, downloads or buttons.
- Inactive scalar widgets read their retained session value. A previously unseen
  key is seeded from the same declared widget default that a mounted widget uses.
- Inactive buttons and submit actions are always false and cannot invoke a
  callback.
- Inactive point, load-case, fatigue-spectrum and bridge editors read the current
  canonical base table directly. They never replay an older widget seed over that
  base table.
- The existing durable scalar, table, catalogue, selection and pending-event
  snapshots remain the canonical unmounted draft. The complete analysis payload,
  signatures, freshness checks, autosave and report generation continue to use
  that draft rather than candidate-selected visible state.
- Stage selection remains a session preference, not a project calculation input.

## Responsive and performance evidence

Browser evidence is required at 390, 768, 1280 and 1920 CSS pixels. At every
width the stage selector must remain within the document width, expose the full
selected label and require no horizontal tab scrolling. The five options and
their order must remain discoverable from the selector.

AppTest evidence must show that representative widget identities from every
inactive sibling are absent from the current element tree, while navigating back
restores their exact retained values. Unit evidence must independently show that
only the selected lazy container delegates and that inactive defaults, buttons,
children and tables are inert.

## Failure and recovery branches

- An interrupted Inputs build restores the last complete engineering snapshot but
  retains the newly selected outer/material navigation value.
- Navigating Inputs -> Analysis -> Inputs retains both selection keys and every
  completed edit.
- A loaded project or autosave can seed an inactive widget without a competing
  widget default warning; the value appears unchanged when its pane is mounted.
- Invalid engineering inputs remain invalid in the returned payload even when the
  owning pane is not mounted. A valid unrelated active pane cannot mask them.

## Explicit exclusions

- No solver, formula, result, provenance, report/manual content, project schema,
  package, workflow, version or release change.
- No calculation-trace restoration or optional trace mode.
- Fragment-scoped reruns and batching/commit boundaries remain PR-12B/F-027.
- Opt-in phase telemetry and numeric browser budgets remain PR-12C/F-028.
- No parallel session-state writes, broad caching, PR-13/PR-14 or v0.93 work.
