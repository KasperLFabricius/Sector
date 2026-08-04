# PR-11B / F-041 figure and table publication acceptance

## Exact base and boundary

- Exact base: `061d15cda6bb137068bcae2d31a97729500443df`.
- Sector version: `0.91`, unchanged.
- Scope: the retained Streamlit/PDF manual, generated calculation report and
  existing Plotly figure factories only.
- The accepted calculation, report-equation and manual-equation payloads are
  inputs to this slice; no solver, formula, material law, result, verdict,
  standard, project schema or calculation-trace path changes.

## Frozen manual inventory

The fail-closed visible manual contains 327 ordered blocks. Its complete
figure/table inventory is 16 figures and 17 tables, in retained block order.
The contracted identities are:

- Figures: `A2-1`; `A3-1` to `A3-2`; `B4-1` to `B4-3`; `B5-1`;
  `C1-1`; `C3-1` to `C3-3`; `C4-1` to `C4-2`; `C6-1`; and `C8-1`
  to `C8-2`.
- Tables: `A3-1`; `B1-1`; `B3-1` to `B3-2`; `B5-1` to `B5-7`;
  `B6-1`; `C2-1`; `C7-1`; `C8-1`; `D1-1`; and `D3-1`.

`Figure <part><section>-<ordinal>` and
`Table <part><section>-<ordinal>` are globally unique. Figure and table
ordinals are independent and reset only on an authored top-level manual
section. Every item retains one non-empty authored subject. The 17 table
subjects are an exact ordered inventory independent of mutable header wording;
an added, removed or reordered table fails closed.

Both manual surfaces publish, for every retained item:

1. one visible local reference immediately before the item;
2. one stable numbered identity;
3. one visible caption;
4. one local PDF/Markdown destination using the same identity; and
5. the retained figure or table content without value transformation.

When manual figures are deliberately excluded from a PDF build, the numbered
identity, reference, caption and explicit unavailable placeholder remain. No
figure silently disappears from the publication inventory.

## Frozen generated-report contract

The report's existing central `_table` and `_fig` boundaries own every dynamic
item. No caller can create an unnumbered generated-report table or figure
through those accepted boundaries.

- Cover-page tables use section `0`.
- Each `_h1` starts a new numeric report section and resets independent figure
  and table ordinals.
- Subsections contribute a visible subject, but do not reset the ordinals.
- Every logical table receives one number even if it is divided into horizontal
  column panels or vertical page fragments.
- A horizontal panel after the first is explicitly labelled as a continuation
  of the same table, never as a new table.
- Every vertical table fragment repeats the numbered caption, frozen section /
  subsection / assessment context and original header row. Unit text therefore
  repeats exactly with its header rather than being inferred from values.
- Every fragment after the first uses the literal `(continued)` caption state.
- Headerless tables repeat the caption and context without promoting the first
  data row into a header.

Captions and local references are presentation metadata only. Numeric source
cells, escaped literal cells, header order, row order, column order, column
panel order, verdicts and pagination data are retained exactly.

## Grayscale contract

All 17 public Plotly figure factories pass through one deterministic
grayscale finalizer. Existing semantic line dashes, marker symbols and bar
patterns remain authoritative. Only a later visible legend series that would
otherwise duplicate an earlier non-colour cue receives a fallback dash, symbol
or pattern. Consequently distinct visible legend series are not distinguished
by colour alone, while accepted colours and engineering values remain intact.

The finalizer is also applied at the report export boundary, so a direct
caller-provided Plotly figure receives the same protection. Non-Plotly test
doubles and timeout paths remain inert.

## Failure and hostile boundaries

- A manual item before a part/top-level section is rejected.
- An unknown publication kind, empty number or empty caption is rejected.
- A changed manual table cardinality is rejected.
- Duplicate manual labels or anchors are rejected.
- Split fragments retain independent caption rows; continuation mutation cannot
  remove the leading fragment's sole PDF anchor.
- User-controlled report section text is converted to plain text and escaped
  again before caption publication.
- Failed/timed-out report figure export remains a truthful report failure and
  does not fabricate an image or captioned result.

## Focused evidence

- `tests/test_publication_figure_table.py`: exact inventory; label/anchor
  uniqueness; Streamlit/PDF parity; resolved PDF links; report numbering;
  repeated units; continuation captions; figure captions/references; complete
  public-factory finalization; line/marker/bar monochrome adversaries.
- `tests/test_publication_table_pagination.py`: retained fragmentation,
  tall-row, context, assessment and headerless-table contracts with the new
  repeated caption row.
- `tests/test_manual.py` and `tests/test_manual_equation_publication.py`:
  complete retained manual/equation behavior.
- `tests/test_report.py` and `tests/test_report_rendered.py`: complete retained
  report behavior and rendered numeric evidence.
- `tests/test_viz.py`: retained figure semantics and visual identities.

## Explicit exclusions

- F-042 shared publication styling and structural/raster PDF preflight remain
  PR-11C scope.
- The Plotly/Kaleido server `kopts` warning is recorded for PR-11C, where the
  shared PDF export/preflight path is owned.
- No calculation-trace restoration or optional trace toggle.
- No PR-12+, packaging, signing, release, version or v0.93 roadmap work.
