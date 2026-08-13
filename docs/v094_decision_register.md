# Sector v0.94 decision register

## Record authority

This register freezes the owner's approved decisions for the Sector v0.94
programme.

- Programme baseline: `main@c1086a2cb8b20a8339ae72bf30218b0b8c6c4dfe`
- Baseline tree: `1ac7905eb5e6fd48cce50def16f769a7e8458be0`
- Baseline product version: Sector 0.93
- Decision freeze date: 2026-08-13
- Target release: Sector 0.94
- Detailed contract: [Sector v0.94 PR programme](v094_pr_programme.md)

This programme is implementation QA, not engineering certification. A
qualified engineer remains responsible for standard applicability, inputs,
modelling, independent verification, design judgement and acceptance of every
result.

## Owner decisions

| ID | Frozen decision | Boundary | Acceptance evidence | Owning PR |
|---|---|---|---|---|
| D094-001 | Raise the product version only after the full PR-14 gate passes. | All earlier slices remain 0.94 development candidates with product version 0.93. | Exact-head version, identity, source-release and package checks. | PR-14 |
| D094-002 | Use minimum change-specific testing during development. | Full static, numerical, UI, publication and packaging gates are deferred to PR-14, not omitted. | Per-PR evidence plus final full-gate receipt. | All; PR-14 closes |
| D094-003 | Preserve supplied review artifacts by hash and reproduce their behaviours with repository-native fixtures. | Confidential/source PDFs and screenshots are not committed. | Fixture provenance and family tests. | PR-01, PR-02, PR-03, PR-10, PR-11, PR-12 |
| D094-004 | Fix the N-M endpoint construction without loosening convergence. | First and last samples use exact endpoints; interior mechanics remain unchanged. | Prestressed-section branch and endpoint oracle. | PR-02 |
| D094-005 | Exact-zero fatigue increments produce exact-zero damage. | Do not use a generic stress cutoff that masks genuine non-zero cycles. | Zero and adversarial near-zero fatigue tests. | PR-03 |
| D094-006 | Separate Miner damage from proof/yield stress utilisation in every result surface. | Status and percentages retain their existing engineering meaning. | Cross-surface fatigue result tests. | PR-03 |
| D094-007 | Every Eurocode-derived input tooltip identifies exact document, edition and clause/table/formula. | Source metadata follows the selected design basis and is verified against inspected licensed material and current official status. | Registry completeness and source-binding tests. | PR-04 |
| D094-008 | Move the optional permitted crack width to Analysis settings and share it across ordinary and heightened checks. | Ordinary calculation remains possible without a criterion; heightened control requires it. | Schema, solver, UI, report and round-trip tests. | PR-05, PR-06 |
| D094-009 | Introduce project schema 25 with conditional schema-24 migration. | Identical or blank legacy criteria migrate directly; conflicting populated values migrate to the conservative minimum and produce a visible migration warning without changing the source file. | Migration equivalence, conservative-conflict warning and source-integrity tests. | PR-05 |
| D094-010 | Calculate fine and coarse heightened crack systems together. | Each has its own effective tension area and a governing comparison is published without suppressing the other branch. | Independent Formula 7.100 NA benchmarks and dual-branch publication tests. | PR-06 |
| D094-011 | Derive heightened diameter, modulus and provided area from ordinary crack evidence. | The sole crack-enabled case is selected automatically; otherwise the user selects a reference case. Diameter follows the ordinary override or the largest contributing mild bar, modulus is the conservative minimum for contributing mild materials, and provided area is their retained sum. Element/material provenance is retained and missing evidence fails closed. | Provenance, mixed-material, reference-case and stale-evidence tests. | PR-06 |
| D094-012 | Render blocking validation as typed, individually navigable issues. | Navigation guarantees workspace and input-stage routing; native editors need not provide unsupported exact-cell focus. | Unit and AppTest navigation/state tests. | PR-07 |
| D094-013 | Replace the material-family dropdown with stateful tabs. | Only the active family mounts expensive controls. | Host, AppTest and hidden-work tests. | PR-08 |
| D094-014 | Move every report-related input, metadata field, option, generation control and download to a peer Report workspace right of Analysis. | Inputs retains only project-file operations and non-report application information. Generation records a frozen input hash and whether current results were reused or recalculated; stale results are never silent. | Navigation, field-ownership, state, hash and report-generation tests. | PR-09 |
| D094-015 | Make Brief a useful compact engineering report. | It includes all relevant analysis inputs and may exceed the former three-page ambition when readability requires it. | Section inventory, cross-profile equality and rendered review. | PR-10 |
| D094-016 | Preserve PR #399's radical correction and eliminate table/subscript overlap. | Report typography is accepted from rendered pages, not text extraction alone. | Layout geometry plus structural-PDF and raster tests. | PR-11 |
| D094-017 | Prevent shear-plot annotation collisions responsively. | Representative widths, signs, axes, tension faces and export dimensions are covered. | Annotation-box geometry and image review. | PR-12 |
| D094-018 | Add trapezoid, L, I, U and annulus Quick Sections, with inverted T as an orientation. | Invalid dimensions fail before geometry construction; generated reinforcement remains inside the valid concrete region. | Exact geometry, preview and project round-trip tests. | PR-13 |
| D094-019 | Sector does not issue a global code-compliance conclusion. | Status vocabulary remains bound to implemented equations and user-specified criteria. | Programme-wide status and absence checks. | All; PR-14 closes |
| D094-020 | A stale persisted report-profile selection must never abort the app. | Current values are retained, recognised legacy values migrate, and any unrecognised `rep_report_content` value is cleared from every live/durable copy, reset to Standard and explained with a visible notice before the keyed widget mounts. Any previously generated report is invalidated. | Hot-session, autosave/project-restore and packaged-startup AppTests using recognised and hostile stale values. | PR-09 |
| D094-021 | Every implementation PR requires a clean GitHub Codex Review on its complete final head before merge. | A review finding is corrected, pushed and followed by `@codex review`; merge is blocked until Codex has reviewed that exact head and has no open finding. Local/subagent review is supplementary only. | Latest-head Codex review identity, zero unresolved Codex threads and clean-review reaction/receipt. | All remaining PRs; PR-01/PR-02 retrospective corrections |

## Standards boundary

The standards source map remains the v0.93 supported concrete basis unless a
v0.94 slice explicitly adds a verified calculation. Before PR-04 and PR-06,
exact clauses and official status are rechecked against the responsible source.
The local Design Basis catalogue is routing evidence, not clause authority.

## Change control

A material change to a frozen decision requires an explicit owner decision, an
updated decision row preserving Git history, an updated acceptance matrix and
affected tests. Implementation details may be refined inside a slice only when
the frozen outcome and engineering boundary do not change.
