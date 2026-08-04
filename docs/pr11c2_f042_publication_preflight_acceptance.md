# PR-11C2 / F-042 acceptance matrix - shared publication preflight

## Candidate identity

- Exact base: `e5c90ccc8c8ce730d534deba9331f8af6fcd36df`.
- Application version: `0.91` (unchanged).
- Family: report/manual publication styling, structural/raster PDF preflight and
  the exact known Plotly/Kaleido server-warning correction.

## Authoritative retained boundary

1. The merged report and manual are the visual and content authority. This slice
   extracts their current typography, spacing, colors and status palette; it does
   not redesign them.
2. Existing report/manual content, formulas, values, verdicts, references,
   numbering, links, outlines, page furniture and figure/table identities remain.
3. Report and manual continue to use their accepted lazy dependency, timeout,
   failure and real-Kaleido export paths.
4. F-042 from the QA roadmap requires complete manual and representative report
   structural/raster preflight and crop regression.

## Frozen style contract

- One ReportLab-independent immutable module owns the shared palette and typed
  report/manual paragraph specifications.
- Report and manual consume those specifications while retaining their exact
  role-specific values, including their deliberately different heading sizes and
  caption spacing.
- The manual module still imports no ReportLab dependency at module load.

## Frozen preflight contract

- Every PDF page has an A4 portrait media box and a content stream.
- Every exact linked `See Figure/Table` identity has one reference and a caption
  on the same page. Supported labels include report `Table 1.10` and manual
  lettered/hyphenated `Table A3-10`; prefixes cannot satisfy shorter labels.
- Every internal link destination resolves to a page in the same PDF.
- Every raster page is nonblank, has plausible ink, preserves a clear edge and
  retains configured header/footer furniture.
- Stable 4-bit greyscale SHA-256 crop fingerprints pin the report overview/page
  furniture and manual cover/footer without hashing volatile figure pixels.

## Warning contract

- Suppress only `UserWarning: The kopts argument is ignored if using a server.`
  when it originates from `plotly.io._kaleido` inside report/manual export.
- Every other warning category, message and source remains visible.
- Export bytes, timeout state and failure behavior remain unchanged.

## Required evidence

- Independent immutable-style, label-boundary, structural-link, crop-tamper and
  exact-warning adversaries.
- Directly affected report/manual/object/rhythm/render fixture tests.
- Complete real-Kaleido manual and representative report through the shared
  preflight with zero known-warning spam.
- ASCII/version, import, static-analysis, base/scope and rejected-ancestry guards.

## Explicit exclusions

- No solver, formula, result, verdict, standard, trace, schema, persistence,
  Streamlit, workflow, package, signing or application-version change.
- No PR-12+, release or v0.93 roadmap implementation.
