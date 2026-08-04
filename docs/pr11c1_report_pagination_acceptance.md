# PR-11C1 report-pagination acceptance

## Exact boundary

- Exact base: `738a31a32868adaedf32ecccbffde43d19de6d09`.
- Sector version: `0.91`, unchanged.
- Family: representative report page and table-object starts only.
- Rejected PR #323 head `3d4ba4b4bf647672adc83c8057e9821f2407aae8`
  is negative evidence only and is excluded from reuse.

## Page-start mechanics

All report-builder forced section starts use ReportLab's native
`NotAtTopPageBreak`. It is a frame-action flowable: it generates a real
`PageBreak` only when the current frame already contains content, and is inert
when automatic pagination has opened a fresh frame. No `PageBreak` subclass or
`wrap()` override is used.

Report table references are preceded by a `55 mm` conditional start reserve.
The reserve covers the reference, caption, frozen section/subsection/assessment
context, header and the minimum readable data fragment. The reference therefore
starts on the same page as its table object. For a table emitted directly after
a subsection heading, the guard is inserted before the heading and reserves
`65 mm`, so the heading moves with the reference/table start without placing a
location-changing flowable inside ReportLab's `keepWithNext` chain.

The stable results overview retains its `7.2 pt` text and uses `1.2 pt` vertical
cell padding so all rows and the governing-note tail fit on report page 2.

## Complete-artifact checks

The 23-figure representative report must retain all existing content, outline,
bookmark, link, repeated-header, formula and engineering checks. In addition:

- every page has semantic body content beyond repeated document furniture;
- every dotted report `See Table` reference shares a page with its table label;
- the results-overview caption and governing note occur on one page; and
- real Plotly/Kaleido rendering and the existing raster checks remain green.

## Explicit exclusions

- Shared report/manual style extraction, structural/raster preflight, manual
  lettered/hyphenated publication labels, visual crop hashes and warning handling
  remain in PR-11C2 / F-042.
- No manual content/layout, solver, formula, result, verdict, standards, schema,
  persistence, Streamlit, workflow, packaging, signing, version or trace work.
