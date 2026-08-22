# PR-02 v0.96 Results Overview acceptance

## Outcome and boundary

PR-02 makes Results Overview a static, fully expanded register of the most
unfavourable retained result for each semantic check type. The selector uses
already retained result rows and never reruns a solver, changes a resistance,
reclassifies an engineering result or creates a section-wide verdict.

The same semantic selector is used by Streamlit and the report overview.
Detailed result views and the deeper report registers retain their load-case,
direction and branch evidence.

## Semantic check types

The overview key describes the comparison or output, not the spelling of a
direction-bearing row label. Consequently:

- plastic bending is one type across all Plastic action sets;
- concrete, reinforcement and tendon stress remain distinct output types;
- long-term and short-term crack-width results remain distinct types;
- all axes, faces and action sets compete within minimum reinforcement;
- each link-detailing criterion is a type, with its governing scope retained;
- `Vx` and `Vy` compete within shear without links and within shear with links;
- `Vx+T` and `Vy+T` compete within the combined sum and each physical
  component; and
- torsion, clear spacing, heightened crack control and grouped fatigue each
  retain their own type.

The selected row is copied unchanged. Its check label therefore preserves the
governing direction or detailing scope, and its action-set ID, result,
criterion, destination view and note remain traceable.

## Applicable results and scope states

An executed or retained result always takes precedence over an inactive
placeholder for the same semantic type. `NOT RUN`, `NOT CALCULATED`,
`NOT APPLICABLE` and `NOT REQUESTED` are scope/calculation-state information;
they cannot override `PASS`, `FAIL`, `INVALID`, `REVIEW`, `STALE`, a retained
calculated output or a user-criterion comparison from another applicable case.

Generic parent placeholders, such as `Shear` or `Elastic stresses`, are omitted
from overview selection when an emitted child result exists for that parent.
They remain available in detailed retained evidence where relevant. Result
payloads for a check disabled in the effective case input are not emitted into
the overview at all.

Within applicable rows, the frozen conservative status order is applied before
eligible utilisation. Within scope states, `NOT RUN`, `NOT CALCULATED`,
`NOT APPLICABLE`, then `NOT REQUESTED` is the display order. Unknown future
statuses remain visible ahead of the known vocabulary. Equal status and
utilisation retain the first canonical row.

## Streamlit presentation

- One static table contains applicable governing result types only.
- The table uses content height and has no interactive body or internal
  vertical scrollbar.
- The compact columns are Check, Governing action, Status, Result, Criterion
  and View. Long notes and source descriptions remain in detailed views.
- Failure and warning counts appear before the table without being combined
  into a project verdict.
- Selected scope/calculation states appear below the table as an always-visible
  compact list, not a second conclusion table or collapsed panel.
- When no applicable result is retained, the view says so explicitly and does
  not imply that the section passes.

## Acceptance matrix

| ID | Adversarial condition | Required result |
|---|---|---|
| O96-01 | Two cases emit the same semantic type with different directions | One row remains; the least favourable status then utilisation governs, with its direction-bearing label and case retained. |
| O96-02 | `NOT RUN` or `NOT APPLICABLE` competes with an executed result | The executed result is selected; the scope state cannot contradict it. |
| O96-03 | A generic parent placeholder competes with a child result | The parent placeholder is not selected for the overview. |
| O96-04 | A disabled check has a stale result payload | No row is emitted for that disabled check. |
| O96-05 | Only scope/calculation-state rows exist for a type | One conservative state remains in the compact scope list, outside the result table. |
| O96-06 | Equal status rows have eligible utilisations | The largest non-negative finite value or positive infinity governs. |
| O96-07 | A future status is retained | It stays visible and cannot disappear behind a known state. |
| O96-08 | Twenty or more result types are displayed | Every row is present in one static content-height table with no fixed pixel height. |
| O96-09 | Counts are shown | They describe visible rows only and state no global compliance conclusion. |
| O96-10 | Repository scope is inspected | No solver, criterion, schema, product version, detailed result or package surface changes. |

## Focused verification

- pure semantic-key, parent/child, status, utilisation, tie and immutability
  tests;
- disabled-payload and mixed zero/non-zero multi-case tests;
- Streamlit static-table and scope-list tests; and
- affected report-overview, programme-contract and version guards.

Complete numerical, publication and package qualification remains at the v0.96
G1 and G2 gates.
