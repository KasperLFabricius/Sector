# PR-11C2A acceptance matrix - publication theme and export noise

## Candidate boundary

- Exact base: `e5c90ccc8c8ce730d534deba9331f8af6fcd36df`.
- Application version: `0.91` (unchanged).
- Family: retained report/manual styling and the exact known Plotly/Kaleido
  server-warning correction.

## Retained authority

1. The merged report and manual are the complete visual authority for this
   extraction; there is no redesign.
2. All current typography, spacing, colors, status colors, content, formulas,
   values, verdicts, numbering, links, figures, tables, timeouts and export
   failures remain unchanged.
3. The eagerly imported manual keeps its ReportLab-lazy dependency boundary.

## Frozen contract

- One ReportLab-independent immutable theme owns the complete extracted palette,
  status-color inventory and every report/manual paragraph role moved in this
  slice.
- The report and manual reconstruct every advertised role from that theme while
  retaining their intentional role-specific differences.
- Only `UserWarning: The kopts argument is ignored if using a server.` from
  `plotly.io._kaleido` is suppressed inside report/manual Plotly export.
- The same message from another module, another message from Kaleido, every
  other warning category, export bytes, failure and timeout remains visible or
  behaves exactly as before.

## Evidence

- Independent immutable-theme, full-role matrix and exact warning-boundary tests.
- Directly affected report/manual/publication layout tests.
- Complete real-Kaleido report and manual renders with no matching warning spam.
- Stable accepted report/manual raster crop comparison, ASCII/version, pyflakes,
  py_compile, import, exact-base, scope and rejected-ancestry guards.

## Exclusions

No PDF structural/raster preflight, solver, formula, result, verdict, standard,
trace, schema, persistence, Streamlit, workflow, package, signing, version,
PR-12+, release or v0.93 roadmap change.
