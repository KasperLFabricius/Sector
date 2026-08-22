# Sector v0.96 decision register

## Record authority

- Programme baseline: `main@df397b2372e2e49b7a2165b0573ea0913e8c94dd`
- Baseline tree: `65eb685d0415cfe7852106838bbf51cc216449ab`
- Baseline product version: Sector 0.95
- Baseline project schema: 26
- Decision freeze date: 2026-08-22
- Target release: Sector 0.96
- Detailed contract: [Sector v0.96 PR programme](v096_pr_programme.md)

Sector remains a transparent internal structural calculation tool. The
engineer controls standard applicability, inputs, modelling, checks and use of
the results. This programme adds no certification, sign-off, approval or
global compliance function.

## Owner decisions

| ID | Frozen decision | Boundary | Acceptance evidence | Owning PR |
|---|---|---|---|---|
| D096-001 | Keep development slices at product version 0.95. | Only PR-10 changes governed version surfaces after G1 passes. | Version/source/manual/package guards. | All; PR-10 closes |
| D096-002 | Use focused affected tests during development. | Complete repository, publication and package gates move to G1/G2; they are not omitted. | Per-PR receipts and final gate receipts. | All; G1/G2 close |
| D096-003 | Preserve the exact accepted base and user artifacts. | No broad staging, destructive reset, `git clean` or reused pytest basetemp. | Base/tree/status and artifact checks. | Every PR |
| D096-004 | Make one coherent bounded change family per PR. | A second unrelated substantive correction is resliced. Any changed head invalidates its review receipt. | Diff/scope audit and exact-head receipt. | Every PR |
| D096-005 | Keep Results Overview fully visible and governing-type based. | One row per stable semantic check type; no fixed-height vertical scroll and no per-case or per-direction conclusion list. | Semantic and Streamlit presentation tests. | PR-02 |
| D096-006 | Derive aggregate states from their applicable child checks. | A parent cannot contradict a failing, passing or executed child; informational/not-run material is separate. No global verdict is added. | Hostile mixed-state fixtures and tie/precedence tests. | PR-02 |
| D096-007 | Define Brief by information depth, not page count. | Retain the complete effective inputs used by every reported active result, governing values and concise limitations. Omit substitutions, derivations, candidate searches and the worked result chain; inactive/unused inputs may be omitted. | Cross-profile input/result inventory. | PR-03 |
| D096-008 | Keep Brief figures exceptional. | Only governing plastic and elastic result plots, when applicable and figures are enabled; no geometry or secondary figures. | Image count/identity tests and raster review. | PR-03 |
| D096-009 | Separate Standard materially from Audit. | Standard has one governing worked calculation per family; Audit retains complete branches, substitutions, candidates and provenance. | Symbolic/numeric/source block inventories and semantic checks. | PR-04 |
| D096-010 | Rewrite Section A Task workflows around user actions and correct stage routing. | Validation guidance points to the actual input stage; report regeneration is not a generic fix. | Manual-source and rendered navigation tests. | PR-05 |
| D096-011 | Keep the end-user manual current and user-facing. | Remove repository/schema/build/release-administration material and former-version narration; retain needed operating and interpretation content. | Vocabulary, content inventory and rendered review. | PR-05 |
| D096-012 | Make `gamma_V` user-controlled for DS/EN 1992-1-1:2023 shear. | Positive finite selected value; 1.40 default; active only for the 2023 no-shear-reinforcement method; first-generation/torsion/combined routes unchanged. | Formula oracles, malformed-input controls and route isolation. | PR-06 |
| D096-013 | Persist and publish the actual `gamma_V`. | Backward load defaults to 1.40; UI, solver, saved project and Standard/Audit agree; schema changes are bounded to PR-06. | Round-trip, migration and cross-surface tests. | PR-06 |
| D096-014 | Tighten standard editions and clauses. | Include consistent 2023 material references, creep coefficient and detailing-checkbox clauses; label project-defined values without inventing a clause. | Reference matrix across UI/manual/report. | PR-07 |
| D096-015 | Use calculation language consistent with Sector's identity. | Replace acceptance/authority/published-evidence wording where it implies approval; preserve precise PASS/FAIL only for implemented comparisons. | User-facing vocabulary gate. | PR-07 |
| D096-016 | Use `‰` on user-facing manual/report surfaces. | Internal identifiers may retain `permille`; copied/extracted text and fonts must preserve `‰`. | Source, PDF and HTML text tests. | PR-07 |
| D096-017 | Improve navigation and page composition without arbitrary page targets. | Visible profile-appropriate contents/cross-links, heading/content colocation, no one-row continuation or orphan subgroup heading, lean boilerplate. | Structural PDF and raster checks. | PR-08 |
| D096-018 | Improve HTML/PDF accessibility without changing calculations. | Skip link, real figure alternatives, accessible math, PDF language metadata and clean extracted text without hidden QA/source markers. | HTML parser, PDF object/text and raster checks. | PR-09 |
| D096-019 | Qualify before and after the version bump. | G1 covers final 0.95 development head; PR-10 is version-only; G2 covers exact 0.96 main before tag/release. | Exact-SHA QA, package, tag and asset receipts. | G1, PR-10, G2 |

## Standards basis for D096-012 and D096-013

The inspected DS/EN 1992-1-1:2023 defines `gamma_V` as the partial factor for
shear and punching resistance without shear reinforcement. Clause 4.3.3 and
Table 4.3 (NDP) give 1.40 for persistent/transient and fatigue situations;
8.2.2 uses the factor in Formulae (8.20) and the strain-based shear-resistance
route. The standard permits national or justified adjusted values, so Sector's
selected 2023 route must expose the actual positive finite calculation input
instead of silently fixing 1.40.

The local document is classified as published but not implemented in the
Danish Design Basis library. Sector therefore presents the 2023 route as a
selectable published method, not as an inferred governing Danish project
basis. The user remains responsible for selecting an applicable basis.

## Change control

A material change to a frozen decision requires an explicit owner decision,
an updated decision row, an updated structured case and focused affected tests.
Implementation detail may be refined inside a slice only when the frozen
outcome, engineering boundary and report-profile philosophy remain unchanged.
