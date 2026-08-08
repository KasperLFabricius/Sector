# Sector v0.93 decision register

## Record authority

This register freezes the owner's decisions for the Sector v0.93 programme.
It is the human-readable, version-controlled source for the corresponding Excel
snapshot. If the two ever disagree, the accepted Git revision of this file is
authoritative until the discrepancy is reviewed and corrected explicitly.

- Programme baseline: `main@decd1232abb0a082639de90726c125dc988e1078`
- Baseline tree: `f25a74a1a234b7b09ddc1be216fe31187333abbd`
- Baseline release: `v0.92-source.1`
- Decision freeze date: 2026-08-08
- Target release: Sector 0.93
- Governing identity: [Sector product identity](product_identity.md)
- Detailed implementation contract: [Sector v0.93 PR programme](v093_pr_programme.md)

The programme is implementation QA, not engineering certification. A qualified
engineer remains responsible for standards applicability, input, modelling,
independent verification, design judgement and acceptance of every result.

## Owner decisions

| ID | Frozen decision | Reason and boundary | Acceptance evidence | Owning PR |
|---|---|---|---|---|
| D093-001 | Raise Sector from 0.92 to 0.93 only after the complete programme gate passes. | Intermediate PRs remain development candidates. The Sector name, description, author, copyright holder and licensee must not drift. | Identity tests and exact-head release gate agree on every version and legal surface. | PR-09 |
| D093-002 | Legacy project compatibility is not required. | Sector is not yet internally QA-released. The next schema is current-only and older schemas fail closed with a clear message; no migration layer is added. | Schema round-trip, unsupported-version and integrity tests. | PR-02 and PR-09 |
| D093-003 | Use risk-based testing during development. | Every PR runs its directly affected tests plus cheap shared guards. Unaffected solver-heavy suites may be skipped on bounded PRs. Full static, numerical, UI, publication and packaging gates run before 0.93. | Per-PR test matrix and final full-gate receipt. | All; PR-09 closes |
| D093-004 | Every editable Streamlit table gets a concise definition block above it and useful plain-text column help. | Streamlit data-editor cells do not render Markdown or LaTeX. A shared metadata source supplies a readable notation guide above the editor while the editor retains accessible plain headers and tooltips. | Metadata completeness tests, AppTest visibility checks and visual review. | PR-04 |
| D093-005 | Table notation uses mathematical formatting outside the editor. | Symbols, subscripts and units are shown with Streamlit math/Markdown in the definition block. Plain-text equivalents remain available for accessibility and copy/paste. | Cross-surface symbol registry tests and UI snapshots. | PR-04 |
| D093-006 | Load action fields accept decimal values. | Native entry accepts unrestricted floating-point precision. Paste/import accepts decimal dot and decimal comma when unambiguous, then stores one canonical numeric value. No value is rounded to the editor step. | Decimal entry, paste/import and round-trip tests. | PR-04 |
| D093-007 | Blank numeric load fields normally mean `0.0`. | Loadcase identity and genuine selectors remain required. Blank action cells are normalized to zero without deleting the user's other row data. Fields where blank has domain meaning, especially an optional crack limit, are explicit exceptions and remain null. | Sparse-row, edit-cycle, calculate, save/load and malformed-cell tests. | PR-04 and PR-06 |
| D093-008 | Deleted catalogue IDs are reusable. | Mild steel, prestress and fatigue families allocate the lowest unused positive suffix. Deleting `M2` permits the next mild-steel family to become `M2`; assigned-family deletion safeguards remain. | M/P/F allocation, deletion and project round-trip tests. | PR-04 |
| D093-009 | Replace the outer input-stage dropdown with tabs without rendering inactive stages. | Stateful Streamlit tabs provide direct navigation. Only the open stage mounts its expensive controls, and completed-input snapshots remain coherent across rapid changes. | Host unit tests, AppTest navigation/freshness tests and performance probe. | PR-05 |
| D093-010 | Make the modelled direction explicit for minimum reinforcement. | The direction is member-relative and is shown before the check, in results, reports and the manual. A project may add an optional alias, but the canonical longitudinal/transverse meaning remains visible. | Shared-label tests and cross-surface publication checks. | PR-05 |
| D093-011 | Ordinary crack-width acceptance is optional. | Sector always displays the calculated crack width when available. With no user criterion it reports `CALCULATED - ACCEPTANCE NOT ASSESSED`. When a positive finite user criterion is supplied, Sector publishes the limit, ratio and a bounded comparison result. It does not infer an exposure limit or global compliance. | Solver, schema, UI, cache-signature, report and manual tests. | PR-06 |
| D093-012 | The first-generation DK/NA heightened crack-control check is separately selectable and its permitted crack width is mandatory. | DS/EN 1992-1-1 DK NA:2024 Formula 7.100 NA uses the specified crack width as an equation operand. It is not silently enabled and is never presented as a 2023 Danish rule. The displayed formula must be independently transcribed and visually checked against the licensed standard; OCR is not an implementation authority. | Dual visual transcription, independent numerical benchmarks, applicability validation and complete calculation evidence. | PR-06 |
| D093-013 | Confinement is deferred beyond 0.93. | No DS/EN 1992-1-1:2023 confinement input, equation, claim, placeholder selector or report wording is added in this programme. | Absence assertions and scope review. | PR-02 and PR-09 |
| D093-014 | Remove bridge-specific checks that require semantic component mapping. | The current brittle Method B region table, box-wall table and web/flange table all require region, wall, web or flange meaning that Sector cannot infer honestly. Their UI, adapter, persistence and publication surfaces are removed together. | Absence, schema and stale-result tests. | PR-02 |
| D093-015 | Keep current- and next-generation concrete design options only where Sector implements a verified calculation. | First-generation bridge references remain EN 1992-2:2005 with the applicable DK NA where supported. The second generation is DS/EN 1992-1-1:2023, whose normative Annex K contains bridge provisions; no fictitious `EN 1992-2:2023` option is created. The 2023 choice is labelled a published project-adoption option with no Danish NA applied. | Registry, citation, selector, report and absence tests. | PR-02 and PR-06 |
| D093-016 | Do not add an inert umbrella compliance selector. | A design option is visible only beside a calculation whose edition-specific equation, defaults, NDP treatment and citation are implemented. Generic section results are not relabelled as complete bridge checks. | Registry-to-solver coverage and UI absence tests. | PR-02 and PR-06 |
| D093-017 | Every complete calculation is presented as a student-readable worked example, including numerical substitution for every meaningful live step. | Crack spacing was one example, not the boundary. Across every calculation family, reports declare the purpose, given values, assumptions, sign convention, derived inputs, equation and source, unit-bearing substitution, branch/cap/iteration decision, interim result, criterion and final interpretation. Reports retain typed operands and branch evidence from the solver and never reconstruct evidence from rounded display values. Pure theory relations may remain symbolic. Iterative algorithms publish their governing equation, search/convergence controls, accepted state and residual rather than an unreadable dump of every trial. | Programme-wide fail-closed calculation-chain inventory, independent numerical traces and pedagogical review by a reader not assumed to know the formulas. | PR-03 and PR-07B |
| D093-018 | Formula typography is checked explicitly in both manuals and reports. | Formulas use a shared Eurocode-style publication grammar: true fractions, radicals, super/subscripts, italic variables, upright operators and descriptive subscripts, equation identity, source, symbol definitions, numerical substitution and result. | Semantic, structural PDF and raster visual gates. | PR-03 and PR-07A |
| D093-019 | Reports offer Brief, Standard and Audit profiles. | Standard is the default. Brief supports rapid review; Standard supports ordinary design review; Audit adds complete calculation evidence and provenance. A profile changes depth, not the engineering result. | Profile policy tests, section inventories and rendered examples. | PR-07B |
| D093-020 | Redesign the manual and reports for progressive disclosure and visual scanability. | The manual separates quick start, workflows, input reference, theory, worked examples, limitations and troubleshooting. Reports lead with project basis, warnings and result summaries before detailed evidence. Dense text is split into short paragraphs, lists, callouts, tables and figures with controlled spacing. | Content inventory, bookmarks/TOC, typography metrics and human visual review. | PR-07B |
| D093-021 | Preserve exact numerical and source provenance across all report profiles. | Brief may omit derivation detail but cannot alter a value, status, method or warning. Standard and Audit expose increasing evidence from the same immutable result model. | Cross-profile equality and provenance tests. | PR-07B |
| D093-022 | A double-clicked BAT in the extracted official source ZIP builds a complete portable Windows distribution without a separate PowerShell command. | The BAT invokes required internal PowerShell itself, authenticates the embedded source manifest when `.git` is absent, builds in isolation and leaves an obvious output folder plus ZIP. It never requires administrator privileges. | Extracted-ZIP end-to-end build, path-with-spaces test, package verification and controlled startup smoke. | PR-08 |
| D093-023 | The distributable Windows application is an unsigned portable application, not a signed Windows production release. | The deliverable contains `Sector.exe` and every required companion file. Its name, README and receipt disclose that it is unsigned and may trigger SmartScreen or corporate policy. It claims no signature, publisher reputation, installer registration or administrator approval. Distribution remains subject to the proprietary licence. | Static identity/signature checks, warning text and release-asset inspection. | PR-08 and PR-09 |
| D093-024 | Distribute the complete ONEDIR package, not `Sector.exe` alone. | The executable depends on its `_internal` payload and notices. The user-facing artifact is a portable folder and ZIP; the executable remains conveniently visible at the folder root. One-file packaging is out of scope unless separately proven safe and reproducible. | Inventory, clean-machine extraction and startup tests. | PR-08 |
| D093-025 | Keep unsigned reproducibility evidence distinct from the portable deliverable. | Existing two-build QA evidence remains an internal gate. A separately named and verified portable archive is the user deliverable. The protected signing workflow remains dormant and has no unsigned fallback. | Workflow topology and artifact-name tests. | PR-08 and PR-09 |
| D093-026 | The decision register is also delivered as `docs/sector_v093_decision_register.xlsx`. | The workbook mirrors these IDs, includes programme ownership and acceptance columns, uses filters/frozen headers, records the programme baseline and canonical Markdown SHA-256, and is pinned by the accepted Git revision. | Workbook formula/error inspection plus rendered review of every sheet. | PR-01 follow-up and PR-09 |
| D093-027 | Sector never issues a global code-compliance conclusion. | Bounded calculation comparisons may use `PASS`/`FAIL` only when a real implemented criterion exists and its source is explicit. Output-only and omitted-criterion states use `CALCULATED`, `NOT ASSESSED`, `NOT APPLICABLE` or `NOT REQUESTED` as appropriate. | Status-taxonomy and absence tests across UI/report/manual. | PR-06, PR-07B and PR-09 |

## Standards status frozen for implementation

| Family | Sector label and scope | Status disclosure | v0.93 boundary |
|---|---|---|---|
| First-generation general concrete | DS/EN 1992-1-1:2004 family with amendments/corrigenda; DK NA:2024 when selected | Current Danish BR18-listed family, subject to project applicability | Retain supported section calculations and add the bounded crack features in D093-011/D093-012. |
| First-generation concrete bridges | DS/EN 1992-2:2005 + AC:2008; DS/EN 1992-2 DK NA:2015 when selected | Current local bridge family, subject to project and owner requirements | Remove component-mapped checks. Whole-section crack provisions may be exposed only with the necessary explicit criterion context. No complete bridge-design claim. |
| Second-generation concrete and bridges | DS/EN 1992-1-1:2023, including normative Annex K | Published reference option; project adoption required; no Danish NA applied | Retain or add only verified non-component equations. Disclose recommended NDP values actually used. No confinement in 0.93. |
| DK heightened crack control | DS/EN 1992-1-1 DK NA:2024 supplementary provision to 7.3.2(1)P, Formula 7.100 NA | First-generation Danish provision only | User selects applicability; permitted crack width is mandatory; publish complete calculation evidence. |

Official transition context is recorded by the European Commission Joint
Research Centre at
[Second generation of the Eurocodes](https://eurocodes.jrc.ec.europa.eu/second-generation-eurocodes).
The current Danish National Annex list is published at
[BR18 National Annexes](https://www.bygningsreglementet.dk/nationale-annekser/nationale-annekser/nationale-annekser?Layout=ShowAll).
Licensed standards remain the equation and clause authority.

## Deferred and excluded items

- DS/EN 1992-1-1:2023 confinement.
- Any automatic semantic component, wall, web, flange or tensile-region mapping.
- Bridge discontinuity, diaphragm, influence-line, traffic-model or complete
  bridge-code coverage claims.
- A generic multidirectional interaction model not already backed by an
  explicit implemented equation.
- Exposure-derived crack limits inferred without an explicit user choice and
  complete required context.
- Legacy project-schema migration.
- Signed installer, MSI, protected certificate use, publisher reputation or
  administrator-managed deployment.
- A single-file executable separated from its required runtime payload.
- Global compliance, certification, approval or sign-off workflow.

## Change control

An implementation detail may be refined within a PR when it does not change a
frozen outcome. Any material change to an ID above requires all of the following:

1. an explicit owner decision;
2. an updated row preserving the former decision and rationale in Git history;
3. an updated PR acceptance matrix and affected tests;
4. an updated Excel snapshot; and
5. a product-identity review before merge.
