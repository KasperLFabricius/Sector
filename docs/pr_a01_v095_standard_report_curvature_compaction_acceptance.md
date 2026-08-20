# PR-A01 v0.95 Standard-report curvature compaction acceptance

## Exact boundary

- Exact base: `53b0069229ad3c5f9b0bf3b65bbcf48541165293`.
- Base tree: `975757fe913980ec9cab57007c3603866cbc6c3f`.
- Product version remains `0.94`; project schema remains `25`.
- Owner outcome: `OA095-001` - compact the Standard-report
  ultimate-curvature substitution while retaining the complete candidate
  evidence.
- Change family: the retained plastic ultimate-curvature selection block in
  generated reports only.

The owner-supplied `sector_testsection.json` reproduction is identified by
SHA-256
`FE9A25649B1DB60F3FE94B592F6F154EECAD1FB6EED8BA66A0F6392499C15AFE`.
On the exact base, its Standard report retains 29 ultimate-curvature candidates
and fails before publication with:

`unbreakable equation atom is 872.46 pt wide; only 309.45 pt is available.`

The owner file is local verification evidence and is not copied into the
repository.

## Authoritative retained evidence

The report consumes only the already-retained selected plastic point:

1. `plastic.points[plastic.worked_point_index].curvature_candidates`, in its
   retained order;
2. each candidate's retained mode, element identity, strain limit, positive
   neutral-axis distance, curvature and selected marker; and
3. the retained `curvature_selection` result.

The report does not rerun a solver, rebuild candidates, reselect a minimum,
deduplicate equal values, reorder candidates or infer a missing selected
marker.

## Frozen publication result

When the current worked block has a non-empty candidate list, a retained
selection and a retained selected candidate:

1. **Complete evidence table.** The existing `Ultimate-curvature candidates`
   table remains present. It retains every candidate exactly once and in the
   original order, with the existing columns, units, precision and selected
   marker.
2. **Governing-candidate calculation.** The existing
   `plastic.worked.curvature-candidate` equation remains unchanged and retains
   the selected candidate's strain limit, neutral-axis distance and curvature.
3. **Stable selection identity.** The selection equation remains
   `plastic.worked.curvature-selection`, with its existing symbolic expression,
   result symbol `kappa_u`, unit `1/m`, symbols, equation number, source note and
   `Uses` link.
4. **Compact numerical substitution.** The unbounded comma-separated list of
   every numeric curvature is replaced by this bounded form:

   `= min(kappa_(i=1:N)) = kappa_g = K 1/m`

   Here `N` is the exact retained candidate count, `g` is the one-based retained
   ordinal of the selected candidate, and `K` is the retained selected
   curvature authored with the existing nine-decimal-place call-site rule and
   then normalized by the existing display-only equation-number compactor.
   For one candidate the population term is `kappa_1` rather than a degenerate
   range.
5. **No evidence relocation.** The compact row points to the complete candidate
   population by count and selected ordinal; the exact numeric operands remain
   in the immediately preceding table. No operand is moved to hidden metadata
   or omitted from the PDF.

Standard is the owner-facing acceptance surface. Audit shares the same complete
worked block and must remain compatible. Brief continues to omit the full
worked derivation under its existing profile policy; PR-A01 does not expand it.

## Acceptance matrix

| ID | Retained condition | Required result |
|---|---|---|
| A01-01 | One selected concrete candidate | Standard PDF succeeds; the one row remains and the compact substitution names candidate 1. |
| A01-02 | Selected candidate is not first | The retained selected ordinal is published; no report-side minimum selection occurs. |
| A01-03 | Equal minimum values with one retained selected marker | Candidate order and both rows remain; the retained selected ordinal wins without tie-breaking. |
| A01-04 | 29-candidate owner reproduction | Standard PDF succeeds without the 872.46 pt atom; all 29 candidate rows and the selected result remain. |
| A01-05 | Synthetic many-candidate retained payload | The substitution width depends only on count, selected ordinal and selected value, not on the number of numeric operands. |
| A01-06 | Standard and Audit profiles | Both complete profiles publish the same compact selection semantics and complete table. |
| A01-07 | Brief profile | Existing omission of the full worked derivation remains unchanged. |
| A01-08 | Candidates or retained selection absent | Existing block omission remains unchanged; no candidate or selection is fabricated. |
| A01-09 | No candidate carries the selected marker | The governing-candidate and selection equations remain omitted as today; the report does not infer one. |
| A01-10 | Candidate list and result are reused by report generation | Source payload is byte/value unchanged after publication. |

## Focused verification

PR-A01 must provide only bounded development evidence:

- direct report tests for one, non-first, tied and 29-candidate retained data;
- equation-flow metadata/text checks for the stable key, roles, compact
  substitution, result and complete candidate table;
- Standard and Audit PDF generation plus Brief exclusion;
- the real Streamlit Report route with the owner reproduction, figures disabled;
- PDF text extraction and rendered-page visual inspection of the owner
  reproduction;
- directly affected equation-contract/layout/report tests; and
- cheap AST/compile, Ruff/policy, ASCII, version, schema, diff and scope guards.

Full repository, coverage, package and release qualification remain deferred to
G1/G2 by D095-002.

## Explicit exclusions

- No generic `EquationFlowable`, parser, wrapping, pagination or table-layout
  change.
- No plastic solver, candidate generation, selection, precision, engineering
  value or verdict change.
- No report-profile policy, navigation, input, Results, manual or UI change.
- No new design basis, equation contract, status, certification or approval
  claim.
- No project persistence/schema, version, workflow, package or release change.
- No PR-A02 through PR-A10 outcome enters this slice.
