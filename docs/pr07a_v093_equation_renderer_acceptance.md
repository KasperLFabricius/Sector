# PR-07A Sector v0.93 shared equation renderer acceptance

Status: candidate acceptance contract for the PR-07A development branch.
PR-06 is merged and PR-07A is in progress. GitHub must record the exact
candidate, tree, checks and eventual squash identity; this document does not
invent remote or final evidence that has not been run.

## Accepted upstream base

- Programme branch: `codex/pr07a-v093-equation-renderer`
- Upstream PR-06 squash revision: `1cf8cf536cc562998fd663a6b082021ace7aa7fb`
- Accepted upstream tree: `f941158eab1f3caa7a61db066236269d69c7a83e`
- Local renderer-core checkpoint: `7ccaa4cbe8a8294076cba548a6ab880327831d4f`
- Local renderer-core tree: `dda487fd44f2a5671013ea80dd5cc62f4f14f842`
- Governing identity: [Sector product identity](product_identity.md)
- Living programme: [Sector v0.93 PR programme](v093_pr_programme.md)
- Decision register: [Sector v0.93 decision register](v093_decision_register.md)
- Upstream candidate contract: [PR-06 crack-control acceptance](pr06_v093_crack_control_acceptance.md)
- Worked-publication authority: [PR-03 textbook-publication acceptance](pr03_v093_textbook_calculation_publication_acceptance.md)

PR-06's exact-head full test/report and two-build unsigned-package gates passed
before merge. PR-06 was squash-merged, the squash tree was verified exactly
equal to the reviewed candidate tree above, and PR-07A's two local publication
commits were then transplanted onto that squash without changing their combined
tree. The renderer-core checkpoint identifies the first shared layout-core
slice. GitHub must still record the final PR-07A candidate and checks.

## Owner-confirmed objective

PR-07A replaces flattened PDF formula approximations with one constrained,
shared Eurocode-style publication renderer. It makes the already selected
worked calculations easier to read without changing an engineering input,
calculation, branch, retained result, governing selection or conclusion.

The shared renderer compiles trusted report markup and the governed manual TeX
subset into a frozen display tree. It measures and draws searchable text plus
vector rules for true fractions, radicals, super/subscripts, italic variables,
upright operators and descriptive subscripts. Unsupported syntax, missing
glyphs and unsafe geometry fail before a partial equation is published.

## Governed corpus and publication density

The governed manual inventory contains exactly 33 equations. All 33 are
compiled and measured before a figure server, output canvas or PDF write can
begin. The Streamlit manual's existing KaTeX and inline-text paths are not
changed.

The governed report inventory contains 143 exact equation-contract identities
across 144 authored `_formula` call sites. Each contract retains its existing
equation key and variant, number, publication role, symbolic relation,
substitution/result requirements, applicability note, symbols, dependencies and
source. A formula is compiled before report numbering, registry or flow state is
mutated, so a rejected display cannot leave partial publication identity behind.

Numerical substitution and result rows use a display-only precision rule.
Ordinary finite decimals are rounded half up to at most three decimal places,
then unnecessary trailing zeros and the decimal point are removed. Thus
`14.000` is published as `14` and `14.500` as `14.5`. If fixed three-decimal
rounding would turn a nonzero operand into zero or change it by more than 0.5%,
the value is instead published in scientific notation with a mantissa of at
most three decimal places. For example, `0.001508` remains `1.508e-3` and
`0.0013` remains `1.3e-3`. This transformation does not alter retained values,
symbolic expressions, sources, notes, tables or engineering calculations.

PR-07A does not change PR-03's global-critical worked-example selector or add a
new worked block. Every calculated case remains available in the existing
compact summaries, while full textbook derivations remain limited to the
globally governing or extremal examples. For example, five eligible Elastic
load cases still produce only the globally largest governed crack-width
examples, including the separate fine and coarse DK/NA branches where the
selected method requires both. Rendering does not turn every case into a worked
chapter or select a less critical result.

## Affected-surface matrix

| Surface | PR-07A change | Frozen boundary and evidence |
| --- | --- | --- |
| Shared PDF equation layout | Add the strict display nodes, report/manual compilers, measurement and ReportLab flowable. | Presentation-only module; no catalogue, result, solver, project or application-state dependency. Unit/property tests pin grammar, geometry, wrapping, alignment and fail-closed errors. |
| PDF fonts and drawing | Embed the required equation faces and draw glyphs and fraction/radical rules as vector content. | Searchable semantic text, `ToUnicode` maps, visible vector operators and absence of equation image XObjects are checked. |
| Manual PDF | Route the 33 governed display equations through the shared flowable after complete preflight. | Exact publication-spine association, identity/expression/result/source order, same-page grouping, lazy import and pre-side-effect failure are checked. Streamlit display remains unchanged. |
| Calculation report PDF | Route all 143 contract identities at 144 authored call sites through the shared flowable inside the existing report-owned equation block. | Existing identity, number, roles, source, symbols, dependencies, bookmarks and audit metadata remain report-owned. Relation axes, long labels, wrapping and formula/source co-location are checked. |
| Reference report fixture | Keep the retained fixture operands internally authoritative while exercising real report layout. | The fixture does not add a solver or publication-side engineering calculation. Semantic, source co-location, vector and browser-free raster checks reject incomplete output. |
| Tests and quality policy | Add renderer, adapter, PDF-structure, extraction and colour/grayscale raster coverage; extend the strict mypy ownership boundary. | Browser-free PDFium, pypdf and ReportLab gates are used locally. No browser, Chrome, Electron, Kaleido or JavaScript runtime is required. |
| Engineering and product surfaces | No intentional change. | Solver equations, retained result contracts and values, governing selection, schema 24, persistence, Streamlit UI, packaging and product version remain outside PR-07A. |

## Semantic, structural and raster contract

Acceptance requires all of the following on the final exact candidate:

- the report and manual compile only their explicitly governed trusted syntax;
- fractions, radicals and scripts have measured structural nodes and vector
  rules rather than flattened text approximations;
- symbolic, substitution and result rows retain a common relation axis, while
  long labels and right-hand operands wrap without changing that axis;
- visible formula text remains searchable through one canonical invisible
  semantic row, with embedded fonts carrying `ToUnicode` maps;
- governed equations use no image XObject and do not depend on raster math;
- equation identity, semantic rows, result, applicability, symbols,
  dependencies and source remain in their contract order;
- numerical substitution and result rows use the bounded three-decimal display
  rule without changing any retained numerical value;
- every report equation identity, complete source paragraph and source-end
  marker occur on the same page;
- every manual equation identity, expression, result and source occur in order
  on one page;
- colour and grayscale PDFium renders remain visible, unclipped, uncollided and
  inside the page bounds; and
- an unsupported construct, unavailable glyph, invalid semantic row,
  unbreakable token or unsafe frame geometry fails closed before publication.

These gates implement decision D093-018: formula typography is checked in both
manuals and reports through the shared grammar, with semantic extraction, PDF
structure and browser-free raster evidence.

## Identity, engineering and programme exclusions

PR-07A is a presentation migration only. It makes no change to a solver,
engineering formula, interim or final result, result-object schema, governing
or extremum selector, project schema, persistence format, freshness signature,
compatibility path, Streamlit input/result UI or application workflow.

It adds no generic calculation trace or evidence payload, trace recorder,
calculation DAG, parallel evaluator, raw iteration history, persisted result
history or replacement for the deliberately retired previous-programme PR-08
machinery. It also implements no part of the current programme's PR-08 portable
Windows packaging scope.

Project schema remains 24 and runtime/publication version remains 0.92. PR-09
owns the transition to version 0.93 after the complete programme gate. PR-07A
does not add a compliance, certification or authority-applicability claim.

## Current local evidence and open gates

The local counts below overlap and must not be summed. They describe the
PR-06-restacked candidate contents before final GitHub qualification:

- 51 shared-renderer tests passed, including contextual classification of
  single-letter `N` and `m` as italic quantities or upright numerical units
  across the governed manual and report forms;
- 563 manual publication/layout tests passed with one deliberate real-figure
  case excluded from the browser-free local group;
- 150 complete browser-free report-module tests passed;
- 243 focused renderer, report-contract, pagination, reference-fixture and
  real-production-route tests
  passed with one deliberate real-figure case excluded;
- the final consolidated report, renderer and production-route regression gate
  passed 411 tests with that same one real-figure case excluded;
- the same 411-test gate passed after its export-failure regression explicitly
  poisoned figure-server startup, with no browser, Chrome, Electron, Kaleido or
  JavaScript process launched by the test run;
- 28 focused numerical-publication tests passed, covering fixed and scientific
  display forms, adjacent variables and units, negative zero, visible vector
  text, searchable PDF text, retained-scope isolation, and the live elastic and
  minimum-reinforcement worked chains;
- the four focused source-end and near-boundary pagination regressions passed;
- one exhaustive catalogue PDF rendered all 143 exact report-contract
  identities with their real labels, symbol inventories and sources, then
  passed semantic-row counts, complete source co-location, vector/no-XObject
  geometry and every-page colour/grayscale raster bounds;
- a separate five-PDF normal-route matrix retained the reference fixture's 88
  raw calls / 87 canonical identities, proved its exact 56-identity gap, and
  closed the real production-branch union to all 143 identities with four
  supplemental increments of 31, 21, 3 and 1;
- 169 Ruff/mypy/dependency/publication-policy and browser-free lazy-startup
  tests passed, and 202 programme/ASCII/retired-trace boundary tests passed;
- an independent final read-only audit closed with no P0-P2 finding; it also
  verified complete identity/source-start/source-end page co-location in all
  five normal-route PDFs and confirmed one globally governing crack-width
  derivation rather than per-case repetition;
- the no-figure reference PDFs rendered as a 41-page manual and a 56-page
  report; the complex C4-1 and C7-5 manual pages and equation-dense report pages
  were inspected in colour and grayscale without clipping or collision; the
  final precision review additionally inspected report pages 14, 38, 45 and 52
  for minimum reinforcement, elastic equilibrium, heightened crack control and
  fatigue, then removed the generated review artifacts; and
- the Ruff policy, strict owned-mypy policy, Python compilation and
  `git diff --check` passed at the recorded local checkpoint.

The current reference report exercises 88 governed equation occurrences across
87 unique report identities. The exhaustive catalogue render closes structural
and raster coverage for all 143 identities, while the normal-report route matrix
separately proves that production report branches can emit every catalogue
identity. The reference report remains the realistic retained-result layout
fixture; the catalogue render is a bounded renderer/layout proof and does not
pretend that synthetic values are engineering examples.

The complete 143-identity layout and production-route matrices passed on the
restacked contents. Independent code, acceptance-record and rendered-page
reviews closed without a remaining product-code P0-P2 defect. Git and GitHub,
rather than this self-referential candidate document, record the immutable
candidate and remote evidence.

Before PR-07A may be merged, GitHub must record the exact PR-07A head/tree and
pass complete coverage, real report/manual rendering and the required two-build
unsigned Windows package workflow on that same head. The merge record must then
retain the accepted squash identity and verify squash-tree parity with the
reviewed candidate tree.
