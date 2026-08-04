# PR-10B1 acceptance matrix - report table layout

Exact base: `af2a835c3da31adc41ac3075dee0fb794ffa305b`

## Frozen scope

- This slice owns the F-019 report-table engine only.
- Every report table retains a minimum 7.2 pt font and lossless cell text.
- Concrete numeric atoms are measured as indivisible evidence. Descriptions,
  trace identities and other machine tokens may wrap losslessly to the authored
  semantic column width.
- Desired widths are reallocated inside the 170 mm A4 frame. A genuinely wider
  table becomes sequential column panels, with the configured leading identity
  columns repeated on every panel.
- Every vertical fragment repeats a frozen section/subsection/status context row
  and its labelled header. Status survives child H2 headings and is cleared by
  the next numbered H1 or replaced by a later status.
- Leading and trailing fragments retain at least three data rows when the relevant
  row group fits. If user-authored tall rows make that bound impossible, the bound
  is relaxed before splitting so valid rows remain recursively pageable.
- Missing cells, changed order, changed values and long identities remain visible;
  the renderer does not filter or reinterpret the retained payload.

## Adversarial matrix

- requested fonts below 7.2 pt;
- long non-numeric machine identities;
- indivisible over-width numeric atoms;
- multi-panel numerical evidence with repeated identity columns;
- H1/H2/status lifecycle and repeated fragment context;
- ordinary multi-page rows where the three-row rule fits;
- first and recursively continued fragments where three tall rows cannot fit;
- a built A4 PDF containing every pasted tall-row identity and terminal token.

## Explicit exclusions

- No loads/settings separation, chapter pagination, formula/reference/status
  spacing, manual spacing, equation numbering, figure/table captions, shared
  publication style, PDF preflight, mechanics, provenance, notation, schema, UI,
  persistence, package, workflow or version change.
- F-032/F-037 remainder is owned by PR-10B2. PR-11 owns F-038/F-039/F-041/F-042.
- Rejected PR heads, including both heads of #292, are negative evidence only and
  are not copied, patched, cherry-picked or entered into this candidate ancestry.
