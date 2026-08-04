# PR-11C1A native report-break acceptance

## Exact boundary

- Exact base: `738a31a32868adaedf32ecccbffde43d19de6d09`.
- Sector version: `0.91`, unchanged.
- Family: report section breaks and the stable results-overview density.
- Rejected heads `3d4ba4b4bf647672adc83c8057e9821f2407aae8`,
  `5f3291e025aeb93348798d6b490ac0c59cd97a8e` and
  `c5dec1cb59ff65dc7af62aee553a7121fa65e68e` are negative evidence only and
  are excluded from reuse.

## Mechanics

All report-builder forced section starts use ReportLab's native
`NotAtTopPageBreak` frame-action flowable. It generates a real `PageBreak` only
when the current frame already contains content and is inert when automatic
pagination has already opened a fresh frame. There is no `PageBreak` subclass,
`wrap()` override, conditional table-start guard or location-changing flowable
inside a kept block.

The stable results overview retains `7.2 pt` type and uses `1.2 pt` vertical cell
padding so the full table and governing-note tail remain on report page 2.

## Complete-artifact checks

The representative report retains all 23 figures and existing engineering,
content, outline, link, formula and raster checks. Its fixture additionally
requires the results overview and governing note on one page.

## Explicit exclusions

- Report table-reference/object colocation and the interacting furniture-only
  table-fragment page are isolated together in PR-11C1B.
- Shared report/manual style, structural/raster preflight, lettered/hyphenated
  manual labels, crop hashes and targeted Kaleido warning suppression remain in
  PR-11C2 / F-042.
- No solver, formula, result, verdict, standards, schema, persistence, Streamlit,
  workflow, packaging, signing, version, trace, PR12+ or v0.93 change.
