# PR-11C / F-042 PDF-publication acceptance

## Exact boundary

- Exact base: `738a31a32868adaedf32ecccbffde43d19de6d09`.
- Sector version: `0.91`, unchanged.
- Family: issued report and user-manual publication only.
- Inputs, solver mechanics, result payloads, engineering verdicts, standard
  applicability, persisted schema and report/manual subject matter are unchanged.
- The retired calculation-trace subsystem is not restored.

## Shared style identity

`app/publication_style.py` is the immutable owner of the report/manual palette,
base type scale, caption scale, minimum table type, spacing grid, A4 margins and
minimum publication-object start height. The two artifacts retain their separate
heading hierarchies, but consume these common tokens rather than maintaining
independent copies.

The minimum published table type is `7.2 pt`. Compact ReportLab subscript and
superscript fragments may use the renderer's `0.8` scale; ordinary words, spaced
numbers and sentences may not cross the minimum.

## Structural preflight

Every complete reference artifact is independently checked for:

- a valid PDF byte stream and exact A4 portrait MediaBox on every page;
- artifact-specific minimum page cardinality;
- minimum body/table type with the explicit compact-script exception;
- intact required numeric tokens;
- table/figure references sharing a page with the referenced object start; and
- no source, project-basis or reference line stranded at a page end.

The complete representative report pins `125.0 %` and `245.000 MPa`; the manual
pins its exact `0.91` version identity. Existing content, figure-cardinality,
outline, bookmark, link, repeated-header and equation contracts remain active.

## Raster preflight and approved crops

PDFium rasterises every page. The shared preflight rejects non-A4 aspect ratios,
implausible ink density, glyphs/rules at page edges, missing report-control
furniture and pages whose only visible marks are repeated header/footer furniture.

The complete fixture also pins two tolerant difference-hash crops:

- the single-page report results overview; and
- the manual concrete-law/mild-steel equation-and-figure page.

These hashes detect material layout drift without requiring byte-identical PDFs.
All generated PDF and PNG evidence is written to a new output directory and no
older QA artifact is removed or overwritten.

## Closed publication defects

- The representative results overview, including its governing-note tail, fits
  on report page 2 instead of stranding three rows on a sparse page 3.
- The `See Table 8.2.` reference remains with the start of Table 8.2.
- A forced section break is inert when automatic pagination already opened a
  fresh page, removing the former furniture-only report page before the bridge
  section while preserving deliberate section starts.

## Kaleido warning boundary

The exact Plotly/Kaleido server warning
`The kopts argument is ignored if using a server.` is suppressed only around the
actual report/manual image-export calls and inside their existing timeout worker
threads. Unrelated `UserWarning` messages remain observable. The persistent
shared Kaleido server, timeout, failure and placeholder behavior is unchanged.

## Focused evidence

- `tests/test_publication_preflight.py`: shared tokens, exact warning boundary,
  A4/type/numeric/reference/source adversaries, body blankness, edge clipping,
  page-break behavior and crop-hash sensitivity.
- `tests/test_publication_vertical_rhythm.py` and
  `tests/test_publication_table_pagination.py`: retained sequencing, spacing,
  context and fragmentation contracts.
- `tests/test_report_rendered.py` and `tests/test_manual_rendered.py`: complete
  real-Kaleido structural/raster/crop preflight of both issued artifacts.
- Existing report, manual, object-publication, grayscale, table-width and
  equation-publication groups remain directly affected evidence.

## Explicit exclusions

- Solver, formula, material, result, verdict or standards changes.
- Streamlit viewport/navigation/performance work owned by PR-12.
- Project schema, persistence, workflow, packaging, signing and release work.
- Generic warning suppression or changes to unrelated Plotly warnings.
- Calculation-trace restoration, optional trace UI/report controls or v0.93 work.
- Sector version `0.92` activation before PR-14 closure.
