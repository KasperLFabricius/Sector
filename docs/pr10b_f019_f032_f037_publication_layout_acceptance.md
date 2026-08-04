# PR-10B F019/F032/F037 publication layout acceptance

## Frozen boundary

This slice changes report/manual publication geometry only: readable tables,
continuation context, balanced page tails, and bounded paragraph/table spacing.
It does not change numerical values, published precision, result cardinality,
solver or trace mechanics, source identity, verdicts, notation semantics,
schemas, or application version.

## Readable table contract

- Every report table uses at least 7.2 point type.
- Column minima are measured from the actual DejaVu Sans paragraph content at
  the issued font size and include explicit 3 point left/right padding.
- Numeric evidence remains an independently measured, uncompressed atom.
  ReportLab-breakable text and machine tokens (including complete trace IDs,
  hashes, and substitutions) remain lossless but may wrap to the semantically
  authored column width, so one token cannot make an A4 panel impossible.
- Flexible requested widths are reallocated before any horizontal split.
- If atomic minima still exceed the 170 mm A4 content width, the table becomes
  sequential column panels. Identity columns repeat; every other column appears
  exactly once; every panel retains every original row and full numeric precision.
- No panel or ordinary table may exceed the A4 content width.

## Pagination and context contract

- Vertically split tables repeat their labelled header.
- Every table owns a frozen context row containing the current numbered section,
  subsection, and any governing status/verdict. That row repeats with the labelled
  column header on every continuation, so context cannot be stale or stranded.
- A chapter-level status survives later child subsections until a replacement
  status or the next numbered section, where it is explicitly cleared.
- Split ranges preserve at least three data rows in both a leading fragment and
  the final tail whenever the table has at least six data rows.
- Loads and Analysis settings are independent pagination units. Long settings
  tables remain splittable rather than being wrapped in a whole-section keep.

## Publication geometry

- Report formula and reference paragraphs gain readable leading, indentation,
  and separation; table cells use 4 point vertical padding; status blocks own
  explicit before/after spacing.
- Manual H1 spacing, small-text leading, and table padding/spacing are increased
  without changing content or navigation.

## Explicit exclusions

- No F040 notation or F034 provenance change.
- No equation IDs, equation-block schema, figure/table numbering, grayscale
  treatment, shared PR-11 style system, or PDF preflight.
- No solver, UI input, persistence, workflow, packaging, or version change.
- No v0.93 roadmap work.
