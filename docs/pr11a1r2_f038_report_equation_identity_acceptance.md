# PR-11A1R2 acceptance matrix - F038 report equation identity

## Candidate identity

- Exact base: `2c75c81b47e55e41a27dcf9d0351773672023ed0`.
- Base tree: `962e702297f7d911dac9adfa8a07c0732727b2f6`.
- Application version: `0.91` (unchanged).
- Family: generated PDF report equation identity, source labels and links only.
- Inventory: all 61 retained `ReportBuilder._formula` call sites.
- Rejected PR #298 heads are negative evidence only and are absent from ancestry.

## Authoritative retained boundary

1. `app/sector_report.py` supplies the accepted report sequence, expression,
   substitution, result/unit and method/source text.
2. Solver and result payloads remain authoritative. This slice changes no
   equation, numerical value, governing selection, verdict or applicability.
3. Existing report, pagination, table-width and vertical-rhythm tests retain all
   accepted report content and layout behavior.
4. Existing `ref` values remain attached to their equations as `Source / method
   note`. Relations without a separate source say so explicitly and never inherit
   a neighbouring standard.

## Frozen identity and numbering contract

- Every retained formula call supplies one code-authored hierarchical key.
- Keys contain lowercase ASCII components separated by `.` or `-`; malformed,
  blank or user-shaped keys fail before publication.
- The one dynamic key is a code-controlled material ordinal. Material IDs,
  action-set names and other user content never enter keys or PDF anchors.
- Runtime identity is section + subsection + hierarchical key. Duplicate keys
  fail within one subsection and may be reused in a later titled subsection.
- Every current governing/reused calculation equation is explicitly numbered.
  Numbering is section-local; an informative unnumbered relation consumes no
  number.
- Public labels combine `Equation (<section>.<sequence>)` and the stable semantic
  `EQ-<HIERARCHICAL.KEY>`. ReportLab anchors contain only authored identity. Dot
  separators encode as `__`, which is outside the accepted key alphabet, while
  authored hyphens remain distinct.

## Frozen source and cross-reference contract

- Every equation publishes a nonblank `Source / method note` line.
- Existing source/method text remains unchanged. An equation with `ref=None`
  publishes `Derived relation; no separate normative source assigned.`
- Cross-references resolve only to a prior equation in the same titled subsection.
- Link labels use the target equation number when numbered and its semantic key
  otherwise. Missing, forward and cross-subsection targets fail explicitly.
- Validation is atomic: a rejected key, source or reference consumes neither an
  identity nor a visible number and appends no flowable.

## Frozen page-cohesion and audit contract

- `_EquationFlowable` is the dedicated one-equation publication boundary and
  remains indivisible when ReportLab releases a taller surrounding group.
- `_keep_from()` preserves this dedicated flowable while retaining the accepted
  flattening of ordinary short-table `KeepTogether` wrappers.
- `_EquationFlowable.getPlainText()` recursively exposes identity, expression,
  substitution, result, links and source to existing direct-child audit traversals.
  The biaxial combined-screen audit therefore sees its summation equation without
  weakening page cohesion or discarding equation metadata.
- Equation anchors do not add entries to the existing section-only PDF outline.

## Focused evidence required

- Identity probes freeze key, anchor, number, section, subsection, public text and
  explicit derived-source behavior.
- Parameterized adversarial probes reject missing sections, malformed/duplicate
  keys, blank sources and unknown references, and prove atomic recovery.
- PDF extraction proves internal numbered link labels survive rendering.
- Grouping probes prove the equation stays nested/auditable and an ordinary
  wrapper still flattens.
- An oversized-group PDF probe proves identity, expression, result and source
  remain together after the outer group releases across pages.
- The exact rejected-head biaxial audit regression must pass independently.
- An AST inventory freezes all 61 retained formula calls and their authored-key
  boundary.
- Complete report, pagination, table-width and vertical-rhythm tests remain green.

## Explicit exclusions

- No F039 standardized expression/substitution/result/unit/symbol block redesign
  (PR-11A2).
- No manual equation catalog, numbering or cross-reference change (PR-11A3).
- No Figure/Table numbering, captions, repeated units or grayscale work (PR-11B).
- No shared manual/report publication-style extraction or structural/raster PDF
  preflight (PR-11C).
- No solver, trace, mechanics, standard applicability, schema, UI, persistence,
  package, workflow, version, PR-12+, or v0.93 change.
