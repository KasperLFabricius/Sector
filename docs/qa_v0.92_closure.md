# Sector v0.92 QA closure ledger

This ledger is the implementation-side index for the sequential v0.92 closure
program. "Implemented" does not mean independently closed. A row becomes
`Merged and independently closed` only after its immutable candidate passes the
frozen independent/adversarial evidence, exact-head Codex Review leaves no
unresolved P1/P2 finding, and its accepted tree is squash-merged and verified on
`main`. The original QA workbook remains the finding index; it is not treated as
a live approval service and this ledger does not invent retrospective approval.

The ledger is updated in every owning PR. Pending rows deliberately do not claim
an oracle, regression, reviewed SHA, or closure that has not yet been produced.

## PR-07 product-simplification reset

PR-07 is governed by [Sector product identity](product_identity.md) and the
[removal-and-preservation map](pr07_removal_preservation_map.md). This owner
decision supersedes the former PR-07 compliance/governance plan: Sector is a
transparent calculation tool, not a compliance-management, approval, sign-off
or code-completeness system. F-011, F-024 and F-029 are therefore deferred
pending explicit owner-led redesign; their former PR-07 implementations are not
acceptance criteria for this reset. F-022's manager/project-authority routing
and F-023's separate multidirectional interaction layer are removed rather than
carried forward.

The owner also confirmed that Sector is unreleased. PR-07 deliberately supports
only its new current project schema; legacy schema-v22 projects, legacy
compliance state and cover-calculator metadata are unsupported. Current-schema
save/load/resave, autosave/download/session behavior, exact numerical-input
retention, and stale/corrupt-result rejection remain required. Sector's product
version remains `0.91`. F-020 and all untracked/ignored QA artifacts remain
excluded from code cleanup and must be preserved.

## Owner-directed calculation-trace retirement

After PR-08, the owner directed complete retirement of the calculation-trace
subsystem because its storage, validation, publication and maintenance cost
outweighed its product value. Accepted R1-R5 PRs
[#311](https://github.com/KasperLFabricius/Sector/pull/311),
[#312](https://github.com/KasperLFabricius/Sector/pull/312),
[#314](https://github.com/KasperLFabricius/Sector/pull/314),
[#315](https://github.com/KasperLFabricius/Sector/pull/315) and
[#316](https://github.com/KasperLFabricius/Sector/pull/316) removed the trace
publication surfaces, family stacks and core residue. Direct solver results and
the calculations displayed in the UI, report and manual remain. No trace payload,
trace view, optional trace toggle or trace report appendix is a current product
requirement. See the [PR-11D reconciliation contract](pr11d_qa_ledger_reconciliation_acceptance.md)
for the exact accepted heads and merge identities.

| Finding | Owning PR | Implementation status | Calculation or presentation behavior | Independent oracle or benchmark | Regression tests and generated artifact evidence | Codex Review iterations / reviewed head | Independent adversarial closure SHA | Merged PR | Accepted residual limitation |
|---|---|---|---|---|---|---|---|---|---|
| F-001 | PR-01 | Implemented on branch; review and closure pending | One winding-independent, scale-aware topology gate now blocks malformed, non-finite, degenerate, repeated, backtracking, self-contacting/crossing, outside/touching/crossing-hole, overlapping, and nested-hole geometry in UI, project I/O, API, raw helpers, and solver entries. | Frozen `G-VALID-CONCAVE`, `G-INVALID-BOWTIE`, `G-INVALID-COLLINEAR`, `G-INVALID-HOLE-OUTSIDE`, and `G-INVALID-HOLE-OVERLAP` cases; test-only exact-rational segment/containment oracle. | `tests/test_geometry_topology.py`; `tests/fixtures/geometry_topology_f001.json`; focused Streamlit pre-solver smoke test; project v14 mixed-winding round trip; existing geometry, solver, shear, torsion, fatigue, capacity, and hand-calculation regressions. | `0ae7e0a7cb2f2c904f3c44c46853db6ef93ac50e`: three actionable comments; terminal-closure analysis normalization, empty mutable-container diagnostic, and orphan-hole rejection implemented for re-review. | Pending | Pending | Exact terminal closure markers and forward intermediate collinear vertices remain valid; raw winding/order is preserved, terminal markers are removed from analysis copies, and analysis rings are oriented canonically. |
| F-002 | PR-07 reset | Corrective implementation; independent re-closure pending | Torsional cracking uses a distinct direct positive-finite `gamma_ct` input rather than `gamma_c`; EN starts at 1.50 and DK/NA at 1.70, with custom values retained without approval or authority routing. Built-in, NumPy and Pandas Boolean scalars are malformed inputs, not coefficients. | 300 x 600 mm C35 tube (`Ak=0.1 m2`, `tef=100 mm`): DK/NA `gamma_ct=1.70` gives `T_Rd,c=26.4349848 kNm`; the rejected `gamma_c=1.45` path gave `30.9927408 kNm`, while rejected NumPy Boolean coercion produced `44.9394742 kNm`. | Focused core default/custom/invalid, Boolean-boundary and demand-between-threshold regressions; current-schema round trip and rejection; Streamlit freshness/default/custom/injected-state plus simultaneous method-change path; report provenance. | Exact corrective head and review are tracked on PR #210; rejected heads `f98130b8091f08fa024d8224cbc3ea6542bdd110`, `26d4a439c9796fbcc8540e2b57a23342994c8512` and review-P1 head `8c1767d4b104b87d2a4f429b4e48bcf258479191` are not accepted. | Pending | Pending | No `gamma0`/`gamma3`, approval, category, authority or legacy-migration route is restored. |
| F-003 | PR-03 | Planned | Apply reinforcement type/bond and `xi1`-weighted prestress contribution to 2023 effective reinforcement ratio. | To be established in owning PR for mixed reinforcement and limiting `xi1` cases. | Pending | Pending | Pending | Pending | None accepted. |
| F-004 | PR-02 | Planned | Edition-aligned Danish fatigue defaults with derived provenance and persistent explicit overrides. | To be established in owning PR from Danish fatigue provisions. | Pending | Pending | Pending | Pending | None accepted. |
| F-005 | PR-07 reset | Simplified by owner product-identity decision | Retain independently useful bridge numerical kernels as direct calculations; remove compliance coverage, applicability gates and unsupported-scope verdicts. | Focused bridge benchmarks plus UI/report/manual absence assertions. | [PR-07 evidence log](#pr-07-evidence-log) | [PR-07 evidence log](#pr-07-evidence-log) | Pending | Pending | Equations, selected method, inputs and warnings remain reproducible. |
| F-006 | PR-07 reset | Simplified by owner product-identity decision | Retain optional brittle Method B, box-wall shear/torsion, fatigue and minimum crack-reinforcement calculations; remove Danish acceptance and manager-decision matrices. | Focused numerical benchmarks plus UI/report/manual absence assertions. | [PR-07 evidence log](#pr-07-evidence-log) | [PR-07 evidence log](#pr-07-evidence-log) | Pending | Pending | Method B warns when the selected Danish standard expects another method, without replacing the user's choice. |
| F-007 | PR-07 reset | Simplified by owner product-identity decision | Retain the direct-tension crack-width calculation as numerical output; remove decompression acceptance and blocking compliance states. | Pure-tension and ordinary combined-action crack regressions plus publication assertions. | [PR-07 evidence log](#pr-07-evidence-log) | [PR-07 evidence log](#pr-07-evidence-log) | Pending | Pending | No crack-width limit or decompression verdict remains. |
| F-008 | PR-07 reset | Simplified by owner product-identity decision | Use the ordinary longitudinal crack calculation, including governing bar stress from combined N+Mx+My; remove the separate multidirectional interaction layer. | Focused combined-action regression and absence assertions for interaction verdicts. | [PR-07 evidence log](#pr-07-evidence-log) | [PR-07 evidence log](#pr-07-evidence-log) | Pending | Pending | Generic cross-direction crack interaction is not calculated. |
| F-009 | PR-07 reset | Implemented; independent closure pending | Retain independent `Vx` and `Vy` demand/resistance checks. Generic cross-direction interaction is explicitly not calculated and has no aggregate verdict. | Directional benchmark tests and UI/report absence assertions. | [PR-07 evidence log](#pr-07-evidence-log) | [PR-07 evidence log](#pr-07-evidence-log) | Pending | Pending | No universal cross-direction interaction rule is inferred. |
| F-010 | PR-07 reset | Simplified by owner product-identity decision | Retain concrete compression-fatigue equations as a direct user-selected numerical calculation; remove bridge-methodology and project-basis adoption gates. | Focused numerical benchmarks plus UI/report/manual assertions. | [PR-07 evidence log](#pr-07-evidence-log) | [PR-07 evidence log](#pr-07-evidence-log) | Pending | Pending | Actual selected method and inputs remain in calculation provenance. |
| F-011 | Superseded / deferred | Former PR-07 plan superseded by owner product-identity decision | A global conclusion, compliance register or action-closure workflow is outside Sector's calculation-tool identity. Reconsider only through explicit owner-led product redesign. | N/A for this reset; absence is checked across UI/report/manual. | [PR-07 evidence log](#pr-07-evidence-log) | [PR-07 evidence log](#pr-07-evidence-log) | Pending | Pending | Calculation provenance, assumptions, warnings and individual genuine demand/resistance verdicts remain. |
| F-012 | PR-13 | Planned | Add ratcheted coverage, selected Ruff, type, and dependency-security CI gates with owned waivers. | Controlled gate-failure demonstrations to be established in owning PR. | Pending | Pending | Pending | Pending | Temporary waivers must name owner and expiry/exit condition. |
| F-013 | PR-13 | Planned | Type solver/result and standards-routing boundaries and replace broad engineering catches with narrow, traceable failures. | Fault-injection oracle to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-014 | PR-14 | Planned | Add Windows product/version resources, build provenance, legal checks, and a real signing/reputation release gate. | CI metadata and signing-policy inspection to be established in owning PR. | Pending | Pending | Pending | Pending | No signature will be fabricated; unavailable corporate signing authority blocks release. |
| F-015 | PR-14 | Planned | Reduce cold startup through measured lazy loading and provide appropriate signed progress indication. | Cold-import and first-usable-UI timing benchmark to be established in owning PR. | Pending | Pending | Pending | Pending | Managed-endpoint launch requires separately confirmed approved signing path. |
| F-016 | Superseded / retired | Superseded by owner-directed trace retirement | Trace-only combined-elastic iteration diagnostics are not published; retained direct elastic results remain available to the UI/report. | R1-R5 absence checks and retained-result regressions; [reconciliation contract](pr11d_qa_ledger_reconciliation_acceptance.md). | Retirement suites pin absence of `calculation_traces` payloads/views and preservation of direct results. | R1-R5 exact-head reviews; final accepted head `8c79f48365671960e8ad53d584605aca742cd1e5`. | `8c79f48365671960e8ad53d584605aca742cd1e5` | [#311](https://github.com/KasperLFabricius/Sector/pull/311) through [#316](https://github.com/KasperLFabricius/Sector/pull/316) | Verification is by direct outputs, report/manual equations and hand calculations, not a retained trace bundle. |
| F-017 | PR-09A | Merged and independently closed | Manual geometry-validation claims now match the accepted topology gate and its actual retained behavior. | Cross-check against `docs/geometry_topology.md` and the accepted geometry fixtures. | Manual content and geometry-document regressions on the immutable candidate. | Exact-head clean review at `8de002c85e4bac0c24b6075319c519cfb44f71ba`. | `8de002c85e4bac0c24b6075319c519cfb44f71ba` | [#283](https://github.com/KasperLFabricius/Sector/pull/283) | Documentation describes implemented behavior; it does not broaden geometry mechanics. |
| F-018 | PR-12 | Planned | Replace clipped narrow navigation with a discoverable responsive selector/overflow design. | Browser viewport evidence at 390/768/1280/1920 px to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-019 | PR-10B1b / PR-10B2 | Merged and independently closed | Long tables retain context across row/in-row splits; Loads and Analysis settings start predictably without furniture-only pages. | Direct ReportLab split probes plus controlled small/default/dense PDFs. | [Pagination contract](pr10b1b_f019_table_pagination_acceptance.md) and [publication-rhythm contract](pr10b2_f019_f037_publication_rhythm_acceptance.md), with extraction/raster checks. | Exact-head clean reviews at `bda00599af25f2d3b1869b1469987db85cc0e1de` and `48faa10364473c2245b4a04632fafa7f32f052cf`. | `bda00599af25f2d3b1869b1469987db85cc0e1de`<br>`48faa10364473c2245b4a04632fafa7f32f052cf` | [#296](https://github.com/KasperLFabricius/Sector/pull/296), [#297](https://github.com/KasperLFabricius/Sector/pull/297) | Accepted table width/panel identities and authored content remain unchanged. |
| F-020 | Excluded | Excluded - non-code local build hygiene; user-directed exclusion | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| F-021 | PR-14 | Planned | Implement a defensible reproducibility model and controlled-build timestamp/hash behavior. | Two controlled Windows-build comparison to be established in owning PR. | Pending | Pending | Pending | Pending | Byte identity will not be claimed unless demonstrated. |
| F-022 | PR-07 reset | Removed by owner product-identity decision | Infrastructure-manager, asset-class and project-basis source routing are absent. Standards and methods are direct user calculation choices. | UI/schema/report/manual absence assertions. | [PR-07 evidence log](#pr-07-evidence-log) | [PR-07 evidence log](#pr-07-evidence-log) | Pending | Pending | Method/equation citations and actual input provenance remain. |
| F-023 | PR-07 reset | Removed by owner product-identity decision | Ordinary cracks use longitudinal reinforcement stress from the combined `N+Mx+My` section solution. Independent `Vx`/`Vy` checks remain; separate crack and generic shear interaction overlays are absent. | Combined-action crack regression and independent-direction shear benchmarks. | [PR-07 evidence log](#pr-07-evidence-log) | [PR-07 evidence log](#pr-07-evidence-log) | Pending | Pending | Generic cross-direction interaction is explicitly not calculated. |
| F-024 | Superseded / deferred | Former PR-07 plan superseded by owner product-identity decision | Amendment approval, sign-off, action ownership and closure-state workflows are outside Sector's calculation-tool identity. Reconsider only through explicit owner-led product redesign. | N/A for this reset; absence is checked across UI/report/manual. | [PR-07 evidence log](#pr-07-evidence-log) | [PR-07 evidence log](#pr-07-evidence-log) | Pending | Pending | Project identification, preparer and calculation comments may remain as ordinary report metadata. |
| F-025 | PR-12 | Planned | Prevent whole Inputs-workspace rebuild/stall on ordinary pane changes. | Browser rerun/time-to-idle telemetry to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-026 | PR-12 | Planned | Render only the active input pane while retaining unmounted values in one canonical draft model. | Zero-lost-edit and inactive-payload browser evidence to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-027 | PR-12 | Planned | Use safe fragment-scoped reruns and batching/commit boundaries for active panes. | Rapid-switch, rerun-count, and latest-state calculation/autosave evidence to be established in owning PR. | Pending | Pending | Pending | Pending | Shared state writes will not be parallelized. |
| F-028 | PR-12 | Planned | Add opt-in phase telemetry and browser performance budgets. | Cold/warm p50/p95/max, delta-size, long-task, and rerun benchmark to be established in owning PR. | Pending | Pending | Pending | Pending | Only immutable/static resources may receive broad caching. |
| F-029 | Superseded / deferred | Former PR-07 plan superseded by owner product-identity decision | A compliance-grade authoritative build-information record is deferred pending explicit owner-led redesign. PR-07 retains only provenance needed to reproduce and validate the current calculation. | Current-schema hash/freshness tests plus report/manual version assertions. | [PR-07 evidence log](#pr-07-evidence-log) | [PR-07 evidence log](#pr-07-evidence-log) | Pending | Pending | App version, actual inputs, selected method/equation, action identity and result freshness remain. |
| F-030 | Superseded / retired | Superseded by owner-directed trace retirement | Applied-ray trace internals are not printed; retained plastic demand, capacity, intersection and utilization outputs remain directly published. | R1-R5 absence checks and retained plastic-result regressions; [reconciliation contract](pr11d_qa_ledger_reconciliation_acceptance.md). | Retirement suites pin removal of trace publication without changing accepted plastic mechanics. | R1-R5 exact-head reviews; final accepted head `8c79f48365671960e8ad53d584605aca742cd1e5`. | `8c79f48365671960e8ad53d584605aca742cd1e5` | [#311](https://github.com/KasperLFabricius/Sector/pull/311) through [#316](https://github.com/KasperLFabricius/Sector/pull/316) | Detailed intermediate verification is by the manual/report equations and independent hand comparison. |
| F-031 | Superseded / retired | Superseded by owner-directed trace retirement | Trace-only creep decomposition and iteration payloads are not published; retained elastic result fields used by product surfaces remain. | R1-R5 absence checks and retained elastic/creep-result regressions; [reconciliation contract](pr11d_qa_ledger_reconciliation_acceptance.md). | Retirement suites pin no stale trace residue and no direct-result regression. | R1-R5 exact-head reviews; final accepted head `8c79f48365671960e8ad53d584605aca742cd1e5`. | `8c79f48365671960e8ad53d584605aca742cd1e5` | [#311](https://github.com/KasperLFabricius/Sector/pull/311) through [#316](https://github.com/KasperLFabricius/Sector/pull/316) | No optional trace mode is retained. |
| F-032 | PR-10B1a2 | Merged and independently closed | Report tables retain at least 7.2 pt type, indivisible numeric atoms, explicit row identities and ordered A4-width panels. | Markup-aware width measurement plus small/default/dense PDF token and raster probes. | [F-032 width contract](pr10b1a2_f032_table_widths_acceptance.md) and focused adversarial table fixtures. | Exact-head clean review at `bc74309e193d362ae015fc68e78a802a9e43a87d`. | `bc74309e193d362ae015fc68e78a802a9e43a87d` | [#295](https://github.com/KasperLFabricius/Sector/pull/295) | Vertical pagination and rhythm are owned by the separately accepted F-019/F-037 slices. |
| F-033 | PR-09A | Merged and independently closed | Tendon coordinates and local sign/extreme conventions are defined consistently across publication surfaces. | Symbol/glossary cross-surface identity matrix against retained solver conventions. | Focused manual/report/UI symbol and convention regressions. | Exact-head clean review at `8de002c85e4bac0c24b6075319c519cfb44f71ba`. | `8de002c85e4bac0c24b6075319c519cfb44f71ba` | [#283](https://github.com/KasperLFabricius/Sector/pull/283) | No coordinate transform or solver-mechanics change. |
| F-034 | PR-10A1 | Merged and independently closed | Transverse torsion resistance cites Formula (6.27) with Formula (6.8); longitudinal reinforcement remains Formula (6.28). | Exact retained Design Basis identity and cross-surface provenance snapshot. | [F-034 provenance contract](pr10a1_f034_torsion_provenance_acceptance.md) with UI/manual/report assertions. | Exact-head clean review at `9b5d11a4529581f6404941cca3355d27b637bc58`. | `9b5d11a4529581f6404941cca3355d27b637bc58` | [#290](https://github.com/KasperLFabricius/Sector/pull/290) | Citation-only correction; numerical torsion mechanics are unchanged. |
| F-035 | PR-09A | Merged and independently closed | Curve 2 is labelled user-defined and Curve 3 as the Eurocode design preset across UI/manual/report. | Cross-surface content matrix with exact method identities. | Focused selector, manual and report identity regressions. | Exact-head clean review at `8de002c85e4bac0c24b6075319c519cfb44f71ba`. | `8de002c85e4bac0c24b6075319c519cfb44f71ba` | [#283](https://github.com/KasperLFabricius/Sector/pull/283) | Curve selection remains a direct user choice; no adoption/approval workflow applies. |
| F-036 | PR-09B | Merged and independently closed | Manual documents retained algorithms, tolerances and failure states; one current-schema example and matching hand pack cover every main report family. | Production-independent geometry, plastic, elastic, crack, shear, torsion, detailing, fatigue and bridge oracle. | [F-036 complete acceptance](pr09b_f036_complete_acceptance.md); real download/calculate/report and SHA-256 hand-pack checks. | Exact-head clean review at `204a83b89b1df62779179f6e84c52916673a46db`. | `204a83b89b1df62779179f6e84c52916673a46db` | [#287](https://github.com/KasperLFabricius/Sector/pull/287) | Hand pack demonstrates retained methods; it does not create a second production solver. |
| F-037 | PR-10B2 | Merged and independently closed | Report/manual formula, reference, assessment, heading and table geometry use measured readable vertical rhythm without collisions. | Direct style/flowable probes plus focused text extraction and raster evidence. | [F-019/F-037 rhythm contract](pr10b2_f019_f037_publication_rhythm_acceptance.md). | Exact-head clean review at `48faa10364473c2245b4a04632fafa7f32f052cf`. | `48faa10364473c2245b4a04632fafa7f32f052cf` | [#297](https://github.com/KasperLFabricius/Sector/pull/297) | Authored engineering content and accepted table pagination remain unchanged. |
| F-038 | PR-11A1R2 | Merged and independently closed | All 61 retained report equation call sites have stable section-local identities, numbers, source lines and genuine cross-references. | Complete call-site inventory, duplicate/malformed-key adversaries and PDF destination/reference checks. | [F-038 report-equation identity contract](pr11a1r2_f038_report_equation_identity_acceptance.md). | Exact-head clean review at `257adb0171ef47327300041b580c5a6ed54245ad`. | `257adb0171ef47327300041b580c5a6ed54245ad` | [#299](https://github.com/KasperLFabricius/Sector/pull/299) | Informative unnumbered relations remain allowed and consume no ordinal. |
| F-039 | PR-11A2 / PR-11A3 | Merged and independently closed | Report and manual equations publish stable role-labelled expressions, substitutions/results, units, symbols, dependencies and exact source classifications. | Complete immutable report/manual equation catalogues, dimensional contracts and adversarial renderer-independence tests. | [Report semantic](pr11a2a_f039_report_equation_contract_acceptance.md), [report block](pr11a2b_f039_report_equation_blocks_acceptance.md), [manual location](pr11a3a1l_r6_manual_equation_location_acceptance.md), [manual source](pr11a3a1s_manual_equation_source_acceptance.md), [manual semantic](pr11a3a2_manual_equation_contract_acceptance.md) and [manual publication](pr11a3b_manual_equation_publication_acceptance.md) contracts. | Exact-head clean reviews at all six accepted closure heads. | `bda23848498c21766134d276c1e5824d16cbc66a`<br>`0852b6abb8f95bbb097b117bc4f658406b26ccfd`<br>`75d5e2a07876185abda439344cb2c0472c70e058`<br>`abc2eb7d6ba49116ec51f110383106d1e95e619b`<br>`1b9c87536ba8b2709c1e737b3629f452ef5819d3`<br>`7e88b5599159a699152345151ee9f4eedf3bb12c` | [#301](https://github.com/KasperLFabricius/Sector/pull/301), [#302](https://github.com/KasperLFabricius/Sector/pull/302), [#308](https://github.com/KasperLFabricius/Sector/pull/308), [#309](https://github.com/KasperLFabricius/Sector/pull/309), [#317](https://github.com/KasperLFabricius/Sector/pull/317), [#318](https://github.com/KasperLFabricius/Sector/pull/318) | Only the contracted governing/reused equations are structured; project-defined methods remain uncited. |
| F-040 | PR-10A2 | Merged and independently closed | One trust-aware publication notation layer renders scientific notation, powers, degrees and units while literal user identities remain exact. | Parser/idempotence adversaries plus literal-channel text extraction and raster checks. | [F-040 notation contract](pr10a2_f040_publication_notation_acceptance.md). | Exact-head clean review at `e602901161dfa463145fc10e848f3d197a587d76`. | `e602901161dfa463145fc10e848f3d197a587d76` | [#291](https://github.com/KasperLFabricius/Sector/pull/291) | Publication markup only; numerical values and precision are unchanged. |
| F-041 | PR-11B / PR-11C1 | Merged and independently closed | Stable figure/table identities, captions, references, destinations, continuation context, non-colour plot cues and object/page colocation are enforced. | Complete manual/report object inventories, all 17 Plotly factory probes, grayscale contrast checks and rendered-page colocation adversaries. | [Object contract](pr11b1_f041_object_publication_acceptance.md), [grayscale contract](pr11b2a_f041_factory_grayscale_acceptance.md), [native-break contract](pr11c1a_native_report_breaks_acceptance.md) and [table-colocation contract](pr11c1b_report_table_colocation_acceptance.md). | Exact-head clean reviews at all four accepted closure heads. | `d396238727172849b7ffa6d299fdb5916e05f200`<br>`5cb7e63f3e22d4495c98168c7fe33d989c6b9bb4`<br>`e812dc7c92c31c6bb6f62e287b07502e7f08ceb4`<br>`ab1456e6e2b5f628353053bdc39ba1532a161441` | [#320](https://github.com/KasperLFabricius/Sector/pull/320), [#322](https://github.com/KasperLFabricius/Sector/pull/322), [#325](https://github.com/KasperLFabricius/Sector/pull/325), [#326](https://github.com/KasperLFabricius/Sector/pull/326) | Colour remains supplementary; publication identities are code-authored, not user-derived. |
| F-042 | PR-11C2 | Merged and independently closed | Immutable shared publication theme, exact Kaleido warning suppression, physical-A4 structural checks and complete raster/link preflight cover report/manual PDFs. | Complete role matrix, warning-boundary adversaries, exact reference-to-own-link geometry, destination resolution and rendered-page hashes/crops. | [Theme/warning contract](pr11c2a_publication_theme_acceptance.md) and [structural/raster preflight contract](pr11c2b_publication_preflight_acceptance.md); full real report/manual artifacts. | Exact-head clean reviews at `fa000b0feabdb6355e11b7a339a0b0a5f9ca3d12` and `f95b6d92afea4de92bb8f76820761631566af938`; rejected #327 remains negative evidence only. | `fa000b0feabdb6355e11b7a339a0b0a5f9ca3d12`<br>`f95b6d92afea4de92bb8f76820761631566af938` | [#328](https://github.com/KasperLFabricius/Sector/pull/328), [#329](https://github.com/KasperLFabricius/Sector/pull/329) | Preflight validates retained artifacts; it does not redesign content or suppress any other warning/failure. |

## PR-07 evidence log

- Scope and acceptance boundary: [Sector product identity](product_identity.md)
  and the [PR-07 removal-and-preservation map](pr07_removal_preservation_map.md).
  Product version remains `0.91`. By explicit owner decision, schema v23 is the
  only supported project schema; legacy migration is not an acceptance gate.
- Independent exact-SHA closure rejected
  `f98130b8091f08fa024d8224cbc3ea6542bdd110`: the retained torsional-cracking
  kernel had incorrectly reused `gamma_c=1.45` and inflated the DK/NA benchmark
  from `26.4349848` to `30.9927408 kNm`. The bounded corrective path restores
  only direct `gamma_ct` input/provenance and does not restore compliance,
  approval, authority, category or legacy-migration apparatus.
- Independent re-closure rejected
  `26d4a439c9796fbcc8540e2b57a23342994c8512`: a NumPy Boolean scalar passed
  the raw positive-finite helper as `gamma_ct=1.0`, producing
  `T_Rd,c=44.9394742 kNm` for the same benchmark and allowing a false PASS.
  The bounded correction rejects NumPy/Pandas Boolean scalar types without a
  new production dependency and prevents pre-widget injected Streamlit Boolean
  state from being normalised into a valid-looking coefficient.
- Exact-head Codex Review rejected
  `8c1767d4b104b87d2a4f429b4e48bcf258479191`: a simultaneous selected-method
  change could reseed the managed `gamma_ct` default before the UI inspected
  malformed pre-widget Boolean state. The follow-up captures and invalidates
  the raw value before method-default reseeding; the focused regression freezes
  that ordering.
- Historical reset implementation head:
  `734f267049e115de0a7150915e44eb740db0f39b` on
  [PR #210](https://github.com/KasperLFabricius/Sector/pull/210).
- Historical pre-correction GitHub gate:
  [Sector QA run 30502898335](https://github.com/KasperLFabricius/Sector/actions/runs/30502898335)
  passed with 1,366 tests, 1 skip, a 39-page representative report, a
  31-page manual, evidence upload, Windows package build, package-content
  verification and package upload. The unsigned package was not downloaded or
  launched.
- Focused local evidence covers actual custom partial factors `0.5` and `2.0`
  through materials, current-schema persistence, solver snapshots and report
  text; output-only stress/crack results; ordinary combined `N+Mx+My` crack
  response; independent `Vx`/`Vy`; absence of generic cross-direction verdicts;
  current-schema save/load/resave and hash rejection; removed
  manager/approval/cover-calculator surfaces; retained bridge kernels; and
  stale/corrupt-result rejection. The final review/CI corrective set passed 11
  probes, including reload/calculation behavior and an empty result register.
- Codex Review first identified one P1 at
  `f39d42e55af83fdae52e8605bd89a5e4ceca32bb`: the 2023 bonded-tendon ratio
  was missing from the elastic freshness signature. Commit `29dbfc4` added the
  binding and a regression proving that editing the ratio stales both the
  result and report and forces recomputation. Exact implementation head
  `734f267049e115de0a7150915e44eb740db0f39b` was rereviewed with no major
  issues; the P1 thread was resolved and no P1/P2 thread remained.
- Visual review covered the affected representative report/manual pages and
  pagination boundaries, including the separate directional shear/torsion
  result pages. The latest local fixtures were the 39-page
  `output/pdf/pr07-report-20260730e` report, the 31-page
  `output/pdf/pr07-manual-20260729b` manual and
  `output/pdf/pr07-biaxial-report-20260730a` pages 7-8. The optional live-browser
  check was time-boxed and skipped by supervisor direction after no credible
  crash, stale-result reuse, false numerical verdict or data-loss signal; green
  Streamlit AppTests and existing visual evidence are the UI evidence.
- F-020 and all untracked/ignored QA artifacts remained outside cleanup and
  commits. Independent adversarial closure and merge remain pending. The
  documentation-only head carrying this log must receive its own exact-head
  GitHub gate and Codex Review before the closure request.

## PR-01 evidence log

- Scope: F-001 only.
- Standards routing: not applicable; this PR validates computational geometry
  before any standards method is selected.
- Tolerance and compatibility policy: `docs/geometry_topology.md`.
- Frozen evidence: `tests/fixtures/geometry_topology_f001.json`.
- Independent oracle: exact rational area, segment-intersection, and containment
  predicates implemented only in `tests/test_geometry_topology.py`.
- Focused evidence: 50 topology/entry tests; 142 geometry/section/project tests;
  201 complete Streamlit smoke tests; solver-family, hand-calculation, shear,
  torsion, fatigue, version, packaging, and compatibility batches all green.
- First review fixes: accepted terminal closure markers no longer perturb torsion;
  emptied mutable ring containers retain `GeometryTopologyError`; orphan holes
  are rejected on both project save and load.
- Full local suite after review fixes: 1,399 passed, 1 skipped, 32 rendering
  warnings in 901.32 s with four fixed workers; version remained exactly `0.91`.
- Reviewed v14 project evidence: the supplied `sector_section.json` loads through
  the canonical gate without migration or point reordering.
- Review, CI, independent closure, and merge fields remain pending until they
  refer to the same immutable full head SHA.
