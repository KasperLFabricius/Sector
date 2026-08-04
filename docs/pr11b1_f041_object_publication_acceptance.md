# PR-11B1 / F-041 object-publication acceptance

## Exact boundary

- Exact base: `061d15cda6bb137068bcae2d31a97729500443df`.
- Sector version: `0.91`, unchanged.
- Scope: stable figure/table identities, references, captions, destinations,
  report table continuation and non-splitting figure publication.
- PR #319 head `fd9728bddd5f33a4608e92bd8c9ea628312f57b1`
  is rejected and excluded from reuse.
- Grayscale semantics are deliberately isolated in PR-11B2.

No solver, formula, material, result, verdict, standard, project schema,
calculation-trace, packaging or release behavior changes.

## Manual inventory

The visible manual contains exactly 16 figures and 17 tables. Each contracted
object binds its exact part, top-level section and authored object signature to
its caption before a number is issued. Figure signatures include the factory
identity and caption. Table signatures include the exact ordered headers,
caption and a SHA-256 seal of every ordered header/row/cell string. Missing,
added, moved, reordered, same-header-replaced or identity-mutated objects fail
before publication, including same-cardinality table reorders.

Figure and table ordinals are independent and reset at each authored top-level
section. Their exact retained identities are:

- Figures: `A2-1`; `A3-1` to `A3-2`; `B4-1` to `B4-3`; `B5-1`;
  `C1-1`; `C3-1` to `C3-3`; `C4-1` to `C4-2`; `C6-1`; `C8-1`
  to `C8-2`.
- Tables: `A3-1`; `B1-1`; `B3-1` to `B3-2`; `B5-1` to `B5-7`;
  `B6-1`; `C2-1`; `C7-1`; `C8-1`; `D1-1`; `D3-1`.

Both Streamlit and PDF publish one visible local reference, the same stable
identity, a visible caption and a matching destination for every object. A
figures-disabled manual retains the figure identity, reference, caption and an
explicit unavailable placeholder.

## Generated report

The central `_table` and `_fig` boundaries own all accepted report objects.
Cover objects use section 0. Every top-level report section resets independent
figure and table ordinals; subsections contribute caption subjects without
resetting numbers.

One logical table retains one number across horizontal panels and vertical page
fragments. Each fragment repeats the caption, section/subsection/assessment
context and original unit-bearing header. Later fragments and panels use the
literal `(continued)` state. Headerless tables repeat caption and context but do
not promote a data row. Source values, row/column order and panel order remain
unchanged.

A report figure publishes its reference, image and caption as one non-splitting
block. Export failure remains a truthful report failure and publishes no image.

## Focused evidence

- `tests/test_publication_objects.py`: exact inventory, same-cardinality reorder
  adversaries, PDF/Streamlit parity, resolved links, table fragments and
  indivisible figures.
- `tests/test_publication_table_pagination.py`: retained table fragmentation,
  tall-row, context and headerless-table behavior.
- `tests/test_manual.py`, `tests/test_manual_equation_publication.py`,
  `tests/test_report.py` and `tests/test_report_rendered.py`: affected retained
  publication behavior.

## Explicit exclusions

- Grayscale fallback behavior and public figure-factory finalization: PR-11B2.
- Shared publication style, structural/raster PDF preflight and the targeted
  Plotly/Kaleido server-warning correction: PR-11C / F-042.
- Calculation-trace restoration or an optional trace toggle.
- PR-12+, packaging, signing, release, version or v0.93 roadmap work.
