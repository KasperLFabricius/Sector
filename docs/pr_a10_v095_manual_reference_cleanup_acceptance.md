# PR-A10 v0.95 manual-reference cleanup acceptance

## Outcome and boundary

- Exact base: `52f69d5f232dd9b54b605d5fdd4cf836390cfdd4`.

PR-A10 removes the Complete reproducible reference section, reference-project
download and independent-checking-pack download from the end-user manual. Those
items do not help an engineer operate Sector or interpret a calculation result.

The reference generator, independent numerical oracle, fixture and tests remain
repository QA assets. Their calculations, input hash and coverage are unchanged;
they are simply no longer presented as end-user manual features.

This slice changes no solver, result, schema, persistence, report profile,
design basis, status or product version. The manual remains current-only and
does not narrate earlier Sector behavior.

## Current publication contract

The live manual must still open after the cleanup. The stored content hash for
the Analysis result views table is aligned with its already-published current
Results Overview row. PR-A10 does not change that table; the one-hash correction
repairs the publication contract that otherwise rejected the current manual at
runtime.

## Acceptance matrix

| ID | Condition | Required result |
|---|---|---|
| A10-01 | Manual prose is inspected | No Complete reproducible reference, complete reference project or independent checking pack is described. |
| A10-02 | Manual dialog is opened | No reference-project or checking-pack download is mounted; normal part selection, PDF generation and close controls remain. |
| A10-03 | Repository QA assets are inspected | The reference generator, independent oracle, fixture, input hash and calculation-family tests remain. |
| A10-04 | Current manual publication is validated | The current Results Overview row matches the stored table-content contract and the dialog opens without error. |
| A10-05 | Repository scope is inspected | No calculation, result, schema, report profile, design-basis, status or version change is included. |

## Focused verification

- the complete reference QA test module remains green;
- a live Streamlit AppTest pins removed downloads and retained manual controls;
- the existing manual-dialog test pins the current publication contract; and
- compile, Ruff-policy and diff checks pin the bounded removal.

Full-suite, real-render, package and release qualification remain at the
governed v0.95 release gate.
