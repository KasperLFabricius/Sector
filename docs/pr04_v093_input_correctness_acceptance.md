# PR-04 Sector v0.93 input-correctness acceptance

Status: accepted and merged as PR #385. Reviewed head
`afdd5dd5af7447a592044b029c29d82f2ca4bf18` passed Sector QA run
`31343111358`; squash `d653ba66478425093a10e893ce5cc38447f2db85`
has accepted tree `23514088b253f5e9f81dcec5301fc4498487d23d`.

## Exact accepted base

- Repository revision: `115d78a5fec33bc6d7a614f6a526a17ab32c22e2`
- Repository tree: `14ff5582bb6669d902e0ae4be32fd3bd9d626c84`
- Programme branch: `codex/pr04-v093-input-correctness`
- Governing identity: [Sector product identity](product_identity.md)
- Living programme: [Sector v0.93 PR programme](v093_pr_programme.md)
- Upstream acceptance: [PR-03 textbook-calculation publication acceptance](pr03_v093_textbook_calculation_publication_acceptance.md)

The base revision is the exact squash merge of PR-03. Its tree is identical to
the accepted PR-03 candidate tree.

## Owner-confirmed objective

PR-04 makes Sector's existing editable input tables behave according to one
explicit, reusable contract. Ordinary load actions accept precise decimal input,
blank actions become canonical zero without deleting the row, malformed
nonblank cells remain visible for correction, and optional-null fields remain
absent. Deleted unassigned material and fatigue-detail identifiers become
available again, while identifiers still referenced by the model remain
reserved.

The same field definitions supply the compact mathematical guide above each
editor, accessible plain-text editor help, and the corresponding manual and
report input references. PR-04 changes input handling and explanation; it does
not add or alter an engineering calculation.

## Canonical decimal and blank boundary

The shared field registry assigns every editable field a stable key, plain
label, mathematical symbol, unit, definition, sign convention, source,
required state, blank/default policy and plain help text. Its blank policies
distinguish required values, zero-valued actions, genuine nulls, defaults and
empty text. These distinctions are applied at the canonical Python boundary,
not inferred independently by individual widgets.

Plastic, elastic and grouped-fatigue numeric input accepts one unambiguous dot
or comma decimal separator, including signed and exponent forms. Mixed or
grouped separators, Booleans and non-finite values are rejected as malformed.
An ordinary blank action becomes `0.0`; a required identity or cycle remains
required; an optional-null value does not become zero.

The editor projection preserves entered decimal text and a field-addressed
malformed-value ledger until the user corrects it. Normalization keeps named
sparse rows, and project serialization fails with the precise table, row and
field rather than dropping a malformed nonblank value or encoding it as JSON
null. Calculation and persistence consume canonical full-precision values;
display formatting is not an input-rounding operation.

## Reusable identifier boundary

Mild reinforcement, prestressing steel and fatigue details allocate the lowest
unused positive `M`, `P` or `F` suffix. A stale persisted `next_id` counter does
not permanently reserve a gap. Normalization, add and duplicate operations use
the same deterministic allocator.

Assignments in reinforcement, tendon and applicable capacity inputs are
reserved before catalogue repair or allocation. An assigned identifier cannot
be rebound, deleted or orphaned merely because a catalogue payload is missing,
duplicated or malformed. Only a genuinely unassigned deleted identifier is
reusable.

Quick Section initializes the material catalogues before it writes generated
elements. Generated bars and tendons use the selected live catalogue entry, or
the first live entry when the selection is unavailable; they do not assume that
`M1` or `P1` still exists. This preserves the reservation boundary during a
cold-start builder flow and after a first-suffix catalogue entry was legitimately
deleted.

## Mathematical guides and publication references

The registry covers the seven editable table families: concrete corners,
concrete voids, reinforcement points, tendon points, plastic/capacity cases,
elastic cases and grouped-fatigue spectra. Each input surface receives a compact
field guide immediately above its editor. The guide publishes notation, unit,
meaning, sign convention, source and the exact blank/default rule; long worked
derivations remain outside the editor guide.

Editor column labels and tooltips remain plain and accessible. Manual and report
input-reference tables are generated from the same registry so that a field
cannot acquire a different definition on a publication surface. These additions
do not change PR-03 worked-calculation selection, equation contracts or any
reported engineering value.

## Browser and JavaScript boundary

The custom point-grid JavaScript change is limited to passing validated
plain-text field help to Tabulator's existing header-tooltip property. It adds
no JavaScript dependency, network service, build step, calculation logic or
second source of field semantics. Numeric normalization, issue retention,
identifier allocation and persistence remain authoritative Python behaviour.

The frontend mapping is covered by deterministic payload/source checks, while
the seven guide surfaces and their session lifecycle are covered by Streamlit
AppTest. Local PR-04 acceptance launches no browser, Electron process or
JavaScript runtime. This keeps the browser-facing change narrow without making
an unsupported visual claim or exposing the development environment to a
second GUI process.

## Schema, identity and programme boundaries

PR-04 keeps current-only project schema 24 and the existing schema-23 rejection
policy. It adds no migration, scalar, table or project-version transition. The
runtime and publication version remains 0.92; PR-09 owns the final transition to
0.93 after the complete programme gate.

The formatted PR-01 decision workbook remains the immutable planning snapshot
accepted in PR-01. Updating the living Markdown programme status does not
regenerate, reinterpret or modify that workbook; any reviewed workbook refresh
remains reserved for PR-09.

PR-04 does not implement PR-05 stateful tabs or modelled-direction labels,
PR-06 crack criteria or the heightened DK/NA calculation, any retired generic
trace/evidence system, or PR-08 portable packaging. It changes no solver,
standard capability, calculation status, signing policy or release asset and
makes no compliance or certification claim.

## Acceptance requirements

Acceptance requires:

- sparse named load rows survive editing, calculation and project round trips;
- blank ordinary actions become zero, while required and optional-null fields
  retain their distinct contracts;
- dot and comma decimals retain their canonical precision;
- every malformed nonblank decimal remains visible and produces a precise
  field-addressed error until corrected;
- deleting an unassigned `M2`, `P2` or `F2` makes that identifier the next
  eligible allocation, while every active assignment remains protected;
- a cold-start Quick Section apply creates resolved material assignments, and a
  catalogue without `M1` or `P1` remains valid by assigning generated elements
  to its selected or first live entry;
- all seven editable table families are covered by complete, stable registry
  metadata and consume that metadata on their applicable UI surfaces;
- manual and report input references derive from the same registry and remain
  semantically consistent with the editors;
- schema 24, runtime version 0.92 and existing engineering results remain
  unchanged; and
- the browser-facing payload maps each validated plain-text help value to the
  existing tooltip property, and does not change the canonical Python input
  lifecycle.

## Verification evidence

The final local affected-surface gate on the rebased candidate produced:

- 202 passed: complete field-registry, load-case, fatigue-input,
  material-catalogue, reinforcement-table, point-grid and project-I/O suites;
- 21 passed serially and again with the CI-equivalent four-worker mode: every
  Streamlit node that failed on the first remote candidate plus the cold-start
  and deleted-first-suffix Quick Section regressions;
- 41 passed with four workers: the broader Quick Section, catalogue, prestress,
  tendon, circular-section and box-girder AppTest surface;
- 68 passed: complete manual, manual-equation, manual-rendered and
  publication-object suites plus the reproducible-example manual-download
  regression;
- 141 passed: complete browser-free semantic report suite;
- 190 passed: programme-document, ASCII and product-version guards; and
- Ruff policy, strict owned-mypy policy, focused import/style checks and
  `git diff --check` passed.

The manual-render gate initially exposed a false-positive substring match:
ordinary prose containing `ambiguous` was treated as the standalone leaked
math token `Big`. The guard now uses explicit alphabetic token boundaries,
retains the original standalone-command rejection and passes the full rendered
manual check.

Independent final review also found that the current-schema reader normalized
case and fatigue tables without applying the same strict decimal validation as
the writer. The reader and writer now share one canonical table validator, and
coherently rehashed malformed Plastic, Elastic and fatigue payloads all fail at
ingress. The published reinforcement-point ID rule was also corrected to match
its existing monotonic stable-ID allocator; unlike reusable M/P/F catalogue
identities, point IDs advance above the highest retained suffix and do not fill
deleted gaps.

The first exact-head remote gate then exposed two deterministic acceptance
gaps. The Manual B6-2 wording correction had not refreshed its fail-closed table
content identity; the identity now matches the reviewed table and all 68
manual/publication regressions pass. Quick Section could also be opened before
the first Inputs build, so generated `M1`/`P1` assignments were mistaken for
orphans while missing catalogues were initialized as `M2`/`P2`. Catalogue
initialization now precedes generated assignments and the builder binds them to
an actual live material ID. All 19 affected remote nodes pass locally in both
serial and CI-equivalent four-worker execution.

The next exact-head remote gate passed all 2,975 tests, coverage, policies and
the real-figure report render. Its sole failure was the manual raster preflight:
the new editable-table reference legitimately moves Part D to page 42 and makes
the manual 46 pages, so the contents and footer fingerprints were stale. The
exact Actions artifact was downloaded by digest, rendered with PDFium without a
browser or JavaScript runtime, and visually checked for clipping, overlap,
glyph, alignment and margin defects. The accepted contents and footer crops are
now pinned to those independently reproduced pixels.

No local browser, JavaScript runtime or real Windows package build was launched.
GitHub recorded the exact revision/tree above and the complete coverage, real
report/manual render and unsigned Windows package workflows passed on that head
before merge.
