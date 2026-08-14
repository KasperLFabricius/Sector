# Sector v0.95 decision register

## Record authority

This register freezes the owner's approved decisions for the Sector v0.95
maintenance programme.

- Programme baseline: `main@9abd4c89f71d1379e32085ecc6773e14de882e33`
- Baseline tree: `f5e98754f0f970749919e354957bfa34dd4eb7fe`
- Baseline product version: Sector 0.94
- Baseline project schema: 25
- Decision freeze date: 2026-08-14
- Target release: Sector 0.95
- Detailed contract: [Sector v0.95 PR programme](v095_pr_programme.md)

This is implementation QA, not engineering certification. A qualified engineer
remains responsible for standard applicability, inputs, modelling, independent
verification, design judgement and acceptance of every result.

## Owner decisions

| ID | Frozen decision | Boundary | Acceptance evidence | Owning PR |
|---|---|---|---|---|
| D095-001 | Keep every development slice at product version 0.94. | Only PR-15 may change governed version surfaces after G1 passes. | Runtime, Windows, package, manual and source identity guards. | All; PR-15 closes |
| D095-002 | Use focused change-family testing during development. | Full repository, publication and package gates are deferred to G1 and G2, not omitted. | Per-PR evidence and exact final full-gate receipts. | All; G1/G2 close |
| D095-003 | Prevent accidental early full CI runs. | PR-01 through PR-14 and any G1 repair use `[skip ci]` in candidate and merge subjects. PR-15's candidate also uses `[skip ci]`; its complete reviewed squash-merge message contains no recognised CI-skip directive, so the exact main push triggers G2 once. | Exact commit messages and same-SHA Actions inventory. | PR-01 through PR-15 |
| D095-004 | Require two adversarial reviews on each exact final head. | A fresh independent reviewer and official GitHub Codex Review must both bind the same SHA; any push invalidates both. | SHA-bound receipts. | Every PR |
| D095-005 | Merge only with zero unresolved review findings. | Correct and retrigger after findings; terminal GraphQL/thread-aware inspection must show unchanged head and zero unresolved threads. | Final PR state receipt. | Every PR |
| D095-006 | Reslice instead of broadening. | One substantive correction class is allowed; repeated P1/P2 or a second change family closes or reslices the candidate. | Diff/range audit and review history. | Every PR |
| D095-007 | Fail closed when the plastic M-M envelope excludes the origin. | Zero or small demand cannot receive finite utilisation or PASS unless the accepted closed polygon contains the global origin. | Shifted and centred polygon oracles. | PR-02 |
| D095-008 | Treat prestress-only tension above `fctm` as cracked. | Prestress remains unscaled; an already exceeded tensile limit owns `lambda_cr = 0`, not positive infinity. | Decision-vector and complete section integration tests. | PR-03 |
| D095-009 | Enforce the real-wall cap for hollow torsion. | A user override above the nearest measured wall is rejected before resistance evaluation; below/equal values remain explicit. | Centred and asymmetric hollow-section tests. | PR-04 |
| D095-010 | Use one fail-closed prerequisite contract for combined M-V-T. | Plastic must be converged, closed and checked; active shear/link/torsion results must be valid. Presentation and reports cannot infer a PASS from incomplete payloads. | Direct payload, adapter and cross-surface tests. | PR-05 |
| D095-011 | Reject invalid material definitions at construction. | Strengths, factors, moduli and strains are finite, positive where required and relationship-consistent before use. | Constructor and material-law tests. | PR-06 |
| D095-012 | Reject non-finite section, reinforcement and action input before solving. | Invalid geometry or action cannot yield a converged elastic/plastic state, resistance or PASS. | Section, elastic and typed-error tests. | PR-07 |
| D095-013 | Make plastic sweep endpoints deterministic. | Finite ordered bounds, positive increment, exact endpoints once, and no overshoot; malformed ranges are rejected. | Reversed, zero/negative-step and non-divisible interval tests. | PR-08 |
| D095-014 | Move image export behind a killable, ready process boundary. | Readiness is observed before READY; timeout terminates the owned tree and permits recovery; concurrent callers cannot exchange images; figures-enabled publication fails before partial bytes. | Readiness, hang, concurrency, recovery and issued-artifact tests. | PR-09 |
| D095-015 | Identify uploaded projects by successfully decoded content. | Digest is committed only after decode/parse success; filename is provenance; changed same-name/same-size bytes are not ignored. | Reupload, invalid-then-fixed and same-content tests. | PR-10 |
| D095-016 | Make autosave a locked atomic transaction with visible retry. | Cross-session lock, unique same-directory temp and atomic replace; hash advances only after successful replacement; failure remains due and visible with bounded backoff. | Concurrent writer, injected failure and retry tests. | PR-11 |
| D095-017 | Render point-grid user data as text. | Paste/project/select values never enter `innerHTML`; hostile values remain literal across component reruns. | Formatter contract and real-browser hostile-paste test. | PR-12 |
| D095-018 | Make the manual PDF token guard mandatory. | The supported locked QA environment cannot silently skip the raw-dollar check because an undeclared parser is absent. | Locked-dependency and positive/negative artifact tests. | PR-13 |
| D095-019 | Contain portable build subprocess and manifest failure. | Every phase has a deadline, owned process-tree cleanup and diagnostics; required metadata-copy failure is fatal; dependency ownership matches package imports. | Timeout, manifest, import and diagnostic tests. | PR-14 |
| D095-020 | Defer unproven maintenance cleanup. | Cache, collapsed-work or dead-code changes require a separately approved bounded PR with static/dynamic proof and measurement; otherwise they remain unchanged. | Explicit exclusion or separate acceptance matrix. | Outside frozen sequence |
| D095-021 | Add no feature or global compliance scope. | Sector 0.95 adds no design basis, design method, geometry or certification/approval claim; schema remains 25 unless a later explicit owner decision changes it. | Diff, status-vocabulary and schema guards. | All |
| D095-022 | Qualify and publish in two phases. | G1 qualifies final 0.94 main, PR-15 performs one governed bump, G2 qualifies 0.95, then tag/main/release identity and exactly the qualified portable ZIP plus checksum are proven. | QA, package, tag, asset and digest receipts. | G1, PR-15, G2 |

## Excluded and corrected audit interpretations

Concrete equivalent-amplitude fatigue deliberately treats every supplied pair
as an already-normalised one-million-cycle pair. Its cycle independence is
tested and disclosed, so it is not a v0.95 correctness change. Speculative
performance or dead-code observations do not authorize deletion without the
D095-020 evidence.

## Standards boundary

The supported standards and Danish National Annex routes remain those of
Sector 0.94. This programme corrects software implementation contracts; it does
not extend code coverage. Source applicability and engineering approval remain
outside the product claim.

## Change control

A material change to a frozen decision requires an explicit owner decision, an
updated decision row preserving Git history, an updated structured acceptance
case and affected focused tests. Implementation details may be refined inside a
slice only when its frozen outcome and engineering boundary do not change.
