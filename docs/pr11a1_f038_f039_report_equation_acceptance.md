# PR-11A1 acceptance matrix - F038/F039 report equation publication

## Candidate identity

- Exact base: `2c75c81b47e55e41a27dcf9d0351773672023ed0`.
- Base tree: `962e702297f7d911dac9adfa8a07c0732727b2f6`.
- Application version: `0.91` (unchanged).
- Family: generated PDF report equation identity and block publication only.
- Inventory: all 61 retained `ReportBuilder._formula` call sites.

## Authoritative retained boundary

1. `app/sector_report.py` supplies the accepted report order, retained numerical
   values, substitutions, units, standards strings and derived-result wording.
2. The solver/result payloads remain authoritative. This slice publishes their
   existing evidence and does not reconstruct or alter any calculation.
3. Existing report, pagination, table-width and vertical-rhythm tests retain the
   accepted report eligibility, text, tables, figures, page flow and version.
4. Existing source strings remain assigned to the same equations. A relation with
   no separate normative locator is explicitly derived/project-defined and
   uncited; it never inherits a neighbouring citation.

## Frozen equation identity contract

- Every report formula call supplies a code-authored semantic ID and expression.
- Authored IDs use lowercase hyphenated ASCII tokens. Invalid, blank and
  user-shaped IDs fail before publication.
- Runtime identity is section + subsection + semantic ID. Action-set names,
  material IDs and other user text never enter PDF anchors.
- A repeated semantic ID fails within one section/subsection. The same semantic
  relation may be reused in a later titled subsection or report section.
- The only dynamic authored key is the code-controlled ordinal for repeated
  reinforcement-material design-strength blocks.
- Public IDs are `EQ-<section>.<subsection>-<SEMANTIC-ID>` and anchors are
  `sector-equation-<section>-<subsection>-<semantic-id>`.
- Visible numbering is section-local and consumed only by an explicitly numbered
  governing/reused block. Unnumbered informative relations do not move the
  numbered sequence.

## Frozen equation block contract

- One equation is one `KeepTogether` publication block with explicit roles:
  identity, expression, optional numerical substitution, optional result/units,
  symbol definitions, optional cross-references and source.
- Expression, substitution and result retain the exact accepted engineering
  content. Role labels are publication metadata only.
- Every block requires a nonblank symbol statement. The retained default points to
  the surrounding titled quantity table and report conventions; locally necessary
  definitions remain attached to their equation.
- Every block requires a nonblank source statement. The retained default says the
  relation is derived and has no separate normative citation.
- Long expressions remain ReportLab paragraphs and wrap losslessly inside the
  standard block; no font compaction or literal-token splitting is introduced.
- A surrounding section-level `KeepTogether` retains the nested equation wrapper
  and its metadata. Ordinary short-table wrappers keep the accepted flattening
  behavior, so an oversized outer group can release content without splitting one
  equation into unrelated page fragments.

## Frozen cross-reference and failure contract

- A cross-reference targets a prior equation in the same titled subsection.
- Link labels use the target's visible number when present and otherwise its
  semantic ID. Links resolve to authored ReportLab anchors without adding equation
  entries to the existing section-only PDF outline.
- Missing targets, forward targets, cross-subsection targets, duplicate IDs, blank
  sources and blank symbol definitions fail explicitly.
- Validation is failure-first and atomic: a rejected equation consumes neither an
  identity nor a visible number and appends no flowable.

## Focused evidence required

- Direct block probes freeze identity, roles, anchors, numbering, source, symbols,
  substitution and result publication.
- Parameterized adversarial probes reject malformed IDs, duplicates, blank
  metadata and unknown references, and prove atomic recovery after failure.
- Cross-reference PDF extraction proves numbered link labels survive rendering.
- A narrow-frame probe proves long expressions wrap rather than truncate.
- A grouped-section probe proves `_keep_from()` retains the complete equation
  wrapper and metadata inside its outer grouping boundary.
- An AST inventory freezes all 61 retained call sites, forbids the legacy `ref`
  channel and prevents a new formula from bypassing explicit identity.
- Directly affected complete-report, table-pagination, table-width and vertical-
  rhythm tests must remain green.

## Explicit exclusions

- No manual equation catalog, numbering or cross-reference change (PR-11A2).
- No Figure/Table numbering, captions, repeated units or grayscale work (PR-11B).
- No shared manual/report publication-style extraction or structural/raster PDF
  preflight (PR-11C).
- No solver, formula, result, trace, standards applicability, schema, UI,
  persistence, packaging, workflow, version, PR-12+, or v0.93 change.
