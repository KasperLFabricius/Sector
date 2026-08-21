# PR-A06 v0.95 governing Results Overview acceptance

## Outcome and boundary

PR-A06 replaces the scrolling, repeated multi-case Results Overview with one
always-visible row for each stable check family. The row is selected from the
already retained result-summary rows; no solver is rerun and no result is
reclassified. The selected row keeps the exact action set, direction-bearing
check label, source, result, criterion, destination view and note that produced
it.

The same governing-row selection is used by the application and the Standard
report Results overview. Detailed result views and worked calculations retain
every case. This is a presentation selection only and does not create an
overall section or project conclusion.

PR-A06 adds no calculation, design basis, resistance, criterion, project-save
field, report density mode, product-version change or project-schema change.

## Stable family and ordering

- A stable check family is the exact `(family, check)` pair already emitted by
  `multi_case_summary_rows`.
- Direction-specific labels such as `Shear Vx with links` and
  `Shear Vy with links` remain separate check families. They are not silently
  combined.
- Families appear in the order of their first emitted row.
- Selection never mutates the input rows. The chosen row is copied without
  reconstructing its action-set or direction provenance.

## Complete emitted status vocabulary and precedence

The following is the complete PR-A06 input vocabulary, ordered from most to
least governing within one stable family:

| Rank | Status |
|---:|---|
| 1 | `INVALID` |
| 2 | `FAIL` |
| 3 | `EXCEEDS USER-SPECIFIED LIMIT` |
| 4 | `PROVIDED AREA BELOW CALCULATED REQUIREMENT` |
| 5 | `STALE` |
| 6 | `REVIEW` |
| 7 | `NOT ASSESSED` |
| 8 | `CALCULATED - ACCEPTANCE NOT ASSESSED` |
| 9 | `NOT RUN` |
| 10 | `NOT CALCULATED` |
| 11 | `PASS` |
| 12 | `WITHIN USER-SPECIFIED LIMIT` |
| 13 | `PROVIDED AREA AT LEAST CALCULATED REQUIREMENT` |
| 14 | `CALCULATED` |
| 15 | `NOT APPLICABLE` |
| 16 | `NOT REQUESTED` |

An unrecognised future status is not allowed to disappear behind a known row.
It is selected ahead of the frozen vocabulary and remains visible verbatim so
that the presentation must be updated deliberately.

## Numeric and tie selection

1. Status precedence is applied before numerical comparison.
2. Between rows with the same status, an eligible utilisation is a real,
   non-Boolean, non-negative finite number or positive infinity. Eligible
   utilisation evidence governs missing or malformed utilisation evidence.
3. Between eligible utilisations, the largest value governs. Positive infinity
   is therefore retained as an honest failure boundary.
4. Equal numerical values retain the first canonical emitted row.
5. Equal statuses without eligible numerical evidence also retain the first
   canonical emitted row.
6. NaN, negative values, negative infinity, Boolean values and non-numeric
   values never win a numerical tie.

These rules select exactly one row per stable family. They do not aggregate
utilisations, create a cross-family score or infer a global result.

## Application and publication behavior

- Results Overview contains one dataframe only. The separate per-case register
  is removed from this view; the input tables and detailed result views continue
  to retain every named action set.
- The dataframe height is derived from the complete selected row count without
  a vertical-height cap, so all governing rows are expanded rather than placed
  behind an internal vertical scrollbar.
- Counts above the table describe only the visible governing rows and do not
  constitute a combined verdict.
- The Standard report uses the same selected rows and retains the chosen action
  set, result, criterion and source context. Page splitting remains a print
  layout mechanism, not a different selection rule.
- The manual describes the current one-row-per-family behavior without referring
  to earlier product versions.

## Acceptance matrix

| ID | Condition | Required result |
|---|---|---|
| A06-01 | One row exists for each frozen emitted status | Every status is recognised at its exact precedence rank. |
| A06-02 | A family contains statuses of different ranks | The most governing status is selected, independent of row order. |
| A06-03 | Equal status rows have different eligible utilisations | The largest utilisation is selected. |
| A06-04 | Equal status rows tie numerically | The first emitted row is selected. |
| A06-05 | Equal status rows have no eligible utilisation | The first emitted row is selected. |
| A06-06 | A finite or infinite utilisation competes with malformed evidence | Eligible finite or positive-infinite evidence is selected; malformed evidence cannot govern numerically. |
| A06-07 | A future unrecognised status is present | Its row stays visible ahead of known statuses. |
| A06-08 | Multiple cases emit the same stable check family | Exactly one row remains and retains the selected case, source, view and note. |
| A06-09 | Direction-specific shear or combined rows are emitted | Each exact direction-bearing check label remains its own family and provenance is unchanged. |
| A06-10 | Results Overview is rendered | Exactly one fully expanded governing table is shown; no per-case register table or internal vertical cap remains. |
| A06-11 | Standard Results overview is rendered | It uses the identical governing-row selector and retains the chosen context. |
| A06-12 | Repository scope is inspected | No solver, criterion, detailed-view, schema, version, packaging or unrelated cleanup change is included. |

## Focused verification

- pure selection tests for every status, reversed precedence order, numeric
  boundaries, infinity, malformed values, ties, immutability and provenance;
- multi-case result-presentation tests for selected case and direction labels;
- Streamlit AppTest proving one dataframe and uncapped complete height; and
- focused Standard-report/manual/current-version and programme-contract tests.

The full suite, coverage, portable package and release qualification remain at
the governed G1/G2 gates.
