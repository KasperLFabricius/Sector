# PR-10B1a acceptance matrix - F032 report table widths

Exact base: `af2a835c3da31adc41ac3075dee0fb794ffa305b`

## Frozen scope

- Every generic report table retains at least 7.2 pt type.
- Every concrete numeric word remains indivisible and is measured before layout,
  including when it shares a cell with a unit or annotation.
- Descriptions and machine identities wrap losslessly to their authored semantic
  width; no retained text is shortened, filtered or replaced.
- Preferred column widths are reallocated without crossing content floors.
- Evidence wider than the 170 mm A4 frame is emitted as ordered sequential
  panels. Configured leading identity columns repeat on every panel, and each
  panel identifies its complete set of source column headers.
- Row and column cardinality/order are validated before rendering. Ragged rows,
  width mismatches and a single numeric atom wider than A4 fail explicitly.
- Small and dense panel fixtures preserve every token structurally and rasterise
  with white A4 page edges.

## Explicit exclusions

- No vertical splitting, in-row fragmentation, continuation context, three-row
  fragment rule, Results-overview routing, loads/settings page sequencing,
  formula/status/manual spacing, mechanics, provenance, notation, schema, UI,
  persistence, package, workflow or version change.
- F019 vertical pagination is PR-10B1b. The remaining F019 page rhythm and F037
  vertical geometry are PR-10B2.
- Rejected #292 and #293 heads are negative evidence only and are absent from
  this candidate ancestry.
