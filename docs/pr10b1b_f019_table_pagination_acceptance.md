# PR-10B1b acceptance matrix - F019 vertical table pagination

## Candidate identity

- Exact base: `efd5516212777269be13a48c207ad1ad3c3b3050`.
- Base tree: `9a0b287e8076682063f416031789511ea01fa8f0`.
- Application version: `0.91` (unchanged).
- Family: PDF report publication only.
- Objective: every report data table remains complete and identifiable when it
  crosses an A4 page boundary.

## Authoritative retained boundary

1. `app/sector_report.py` is the current report builder and supplies the actual
   retained table inventory, styles, section order and result-overview payload.
2. ReportLab 4.5.1 `Table.split()` attempts a between-row split first and an
   in-row split second when both are enabled. Its `rowSplitRange` constrains both
   attempts and therefore must be relaxed for structurally tall row groups.
3. Existing accepted report and F032 tests freeze report payload, A4 width,
   minimum table type, column order, composite row identities and panel order.
4. Rejected PR findings are negative evidence only: a tall first/last group must
   not deadlock pagination, and the specialised Results overview must not bypass
   the universal split contract.

## Frozen table contract

- Generic `_table()` output and the specialised Results overview use one
  `_PaginatedReportTable` boundary with `splitByRow=1` and `splitInRow=1`.
- The one-cell assessment banner remains a plain, unsplittable `Table`; it is not
  a data table and does not enter the pagination engine.
- A fragment normally retains at least three data rows before and after a split.
- The three-row range is enabled only when the repeated rows plus the first three
  data rows and the repeated rows plus the final three data rows each fit the full
  A4 content height. A structurally taller group relaxes the range and remains
  splittable, including within one oversized row.
- The fit decision uses the fresh A4 frame's usable height after ReportLab's 6 pt
  top and bottom frame padding, not the current residual frame or the unpadded
  margin-derived document height. A normally sized table can therefore move to
  the next page without weakening the fragment rule, while a near-frame-height
  group still reaches the tall-row fallback instead of deadlocking pagination.
- Every source row and every token in an in-row split is published exactly once.
- Existing F032 width allocation, source-column panel metadata, font floor,
  horizontal padding and A4 width limit remain unchanged.

## Frozen continuation context

- Each data table snapshots the active context when it is authored, in this order:
  `Section N: ...`, `Subsection: ...`, `Assessment: ...`.
- An H1 replaces the section and clears the active subsection and assessment.
- An H2 replaces the subsection but retains the active assessment.
- A new assessment replaces the prior assessment.
- Snapshot rows are prepended to the table, span its complete column inventory and
  repeat on every fragment together with the authored column header.
- Later headings or assessments cannot mutate an already-authored table.
- Assessment context reuses the assessment banner palette. Existing assessment
  banner wording, colour and layout remain unchanged.
- Results-overview status fills retain their source-row alignment after context
  rows are inserted.

## Adversarial evidence required

- Class inventory proves generic tables and Results overview use the pagination
  boundary while the assessment banner does not.
- Direct split probes prove the ordinary leading/trailing three-row rule and its
  tall first/last-group relaxation, including groups in the 12 pt boundary
  between the unpadded document height and the usable fresh-frame height.
- An A4 PDF containing one oversized row proves complete token cardinality across
  in-row fragments and repeated context/header text on every page.
- Context lifecycle and immutability probes cover H1, H2, assessment replacement
  and assessment survival across H2.
- Results-overview probes cover pagination routing and context-adjusted status
  fills.
- A `KeepTogether` probe proves the retained short-table path can release and
  paginate an oversized table without losing content.

## Explicit exclusions

- No width allocation, horizontal panelling or row-identity change (PR-10B1a2).
- No Loads/Analysis-settings page sequencing or report/manual vertical rhythm
  change (PR-10B2).
- No equation identity, equation layout, caption or preflight change (PR-11).
- No mechanics, provenance, solver, schema, UI, persistence, package, workflow,
  version, PR-12+, or v0.93 change.
