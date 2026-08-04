# PR-11C1B acceptance matrix - report table colocation

## Candidate identity

- Base: exact accepted `main` `fbc2acffa5a9fa65be3d78a5def6219004c03038`.
- Application version: `0.91` (unchanged).
- Family: report table publication and directly interacting rendered-page guards.
- Objective: make every report-table reference inseparable from the table object
  without adding a page-position flowable or changing the retained table engine.

## Authoritative retained boundary

1. Current report payloads, table ordering, publication numbering, captions,
   anchors, column panels, repeated context, headers and data rows are retained.
2. `_PaginatedReportTable` remains the single data-table pagination boundary;
   row and in-row splitting, tall-row fallback and continuation captions remain.
3. ReportLab native `NotAtTopPageBreak` remains the only forced report section
   start. Table publication adds no `PageBreak`, `CondPageBreak`, frame break or
   other location-changing flowable.
4. Every issued numeric report-table label has one linked `See Table X.Y.`
   reference, one first caption/destination and captioned continuation fragments.

## Frozen colocation contract

- The first caption row owns the linked reference, destination anchor, exact
  label and caption. ReportLab cannot place the reference without that row.
- A continued fragment repeats `Table X.Y (continued).` and never repeats the
  `See Table X.Y.` reference or the destination anchor.
- Multi-panel tables publish the reference only with panel 1; later panels retain
  their accepted continued identity.
- The dense results-overview table retains `keepWithNext=1`, transferring the
  former reference paragraph's fresh-page behavior to the owned table object so
  the table and governing note continue to share one complete page.
- Short tables may remain kept and long tables may split. Case-heading wrappers
  contain no conditional or native page-break flowable introduced by this slice.
- Rendered-fixture matching uses the complete punctuated label, so `Table 1.10.`
  cannot satisfy a `Table 1.1.` reference.
- Every representative report page retains semantic body content after the exact
  current fixture header, revision, dynamic-version footer and page number are
  removed.

## Adversarial evidence

- Generic long-table first/continuation fragment identity and reference count.
- Per-case action-table kept-block inventory with no location-changing guard.
- Exact `Table 1.1.` versus `Table 1.10.` boundary mutation.
- Furniture-only page rejection with the current dynamic Sector version.
- Complete real-Kaleido representative report plus retained table/object suites.

## Explicit exclusions

- No shared report/manual style, manual label parsing, structural/raster preflight,
  crop hashing or Kaleido warning suppression; those remain PR-11C2/F042.
- No report section-start change, solver, formula, result, verdict, standard,
  schema, persistence, Streamlit, workflow, package, signing or version change.
- No calculation-trace restoration, PR-12+ work or v0.93 roadmap implementation.
