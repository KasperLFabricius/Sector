# Sector v0.92 QA closure ledger

This ledger is the implementation-side index for the sequential v0.92 closure
program. "Implemented" does not mean independently closed. A row becomes closed
only after GitHub CI, current-head Codex Review, and the original independent QA
reviewer all accept the same full commit SHA and that exact head is merged.

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
| F-016 | PR-08 | Planned | Preserve iteration counts for all combined-elastic sub-results and expose meaningful total/max diagnostics. | Independent reconstruction fixture to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-017 | PR-09 | Planned | Correct the manual geometry-validation claim to match the implemented PR-01 behavior. | Manual content comparison against `docs/geometry_topology.md`. | Pending | Pending | Pending | Pending | None accepted. |
| F-018 | PR-12 | Planned | Replace clipped narrow navigation with a discoverable responsive selector/overflow design. | Browser viewport evidence at 390/768/1280/1920 px to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-019 | PR-10 | Planned | Improve continuation titles/status context and page-break/keep-together behavior for long tables. | Controlled small/default/dense PDF layouts to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-020 | Excluded | Excluded — non-code local build hygiene; user-directed exclusion | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| F-021 | PR-14 | Planned | Implement a defensible reproducibility model and controlled-build timestamp/hash behavior. | Two controlled Windows-build comparison to be established in owning PR. | Pending | Pending | Pending | Pending | Byte identity will not be claimed unless demonstrated. |
| F-022 | PR-07 reset | Removed by owner product-identity decision | Infrastructure-manager, asset-class and project-basis source routing are absent. Standards and methods are direct user calculation choices. | UI/schema/report/manual absence assertions. | [PR-07 evidence log](#pr-07-evidence-log) | [PR-07 evidence log](#pr-07-evidence-log) | Pending | Pending | Method/equation citations and actual input provenance remain. |
| F-023 | PR-07 reset | Removed by owner product-identity decision | Ordinary cracks use longitudinal reinforcement stress from the combined `N+Mx+My` section solution. Independent `Vx`/`Vy` checks remain; separate crack and generic shear interaction overlays are absent. | Combined-action crack regression and independent-direction shear benchmarks. | [PR-07 evidence log](#pr-07-evidence-log) | [PR-07 evidence log](#pr-07-evidence-log) | Pending | Pending | Generic cross-direction interaction is explicitly not calculated. |
| F-024 | Superseded / deferred | Former PR-07 plan superseded by owner product-identity decision | Amendment approval, sign-off, action ownership and closure-state workflows are outside Sector's calculation-tool identity. Reconsider only through explicit owner-led product redesign. | N/A for this reset; absence is checked across UI/report/manual. | [PR-07 evidence log](#pr-07-evidence-log) | [PR-07 evidence log](#pr-07-evidence-log) | Pending | Pending | Project identification, preparer and calculation comments may remain as ordinary report metadata. |
| F-025 | PR-12 | Planned | Prevent whole Inputs-workspace rebuild/stall on ordinary pane changes. | Browser rerun/time-to-idle telemetry to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-026 | PR-12 | Planned | Render only the active input pane while retaining unmounted values in one canonical draft model. | Zero-lost-edit and inactive-payload browser evidence to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-027 | PR-12 | Planned | Use safe fragment-scoped reruns and batching/commit boundaries for active panes. | Rapid-switch, rerun-count, and latest-state calculation/autosave evidence to be established in owning PR. | Pending | Pending | Pending | Pending | Shared state writes will not be parallelized. |
| F-028 | PR-12 | Planned | Add opt-in phase telemetry and browser performance budgets. | Cold/warm p50/p95/max, delta-size, long-task, and rerun benchmark to be established in owning PR. | Pending | Pending | Pending | Pending | Only immutable/static resources may receive broad caching. |
| F-029 | Superseded / deferred | Former PR-07 plan superseded by owner product-identity decision | A compliance-grade authoritative build-information record is deferred pending explicit owner-led redesign. PR-07 retains only provenance needed to reproduce and validate the current calculation. | Current-schema hash/freshness tests plus report/manual version assertions. | [PR-07 evidence log](#pr-07-evidence-log) | [PR-07 evidence log](#pr-07-evidence-log) | Pending | Pending | App version, actual inputs, selected method/equation, action identity and result freshness remain. |
| F-030 | PR-08 | Planned | Print applied-ray plastic-utilization bracket vertices, interpolation, intersection, scale, tolerance, and correct sample label. | Between-sweep-angle independent reconstruction fixture to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-031 | PR-08 | Planned | Print complete TOTAL/LONG/DIF/RST1 creep decomposition, material strain planes, contributions, residuals, and iterations. | Independent resultant/stress reconstruction to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-032 | PR-10 | Planned | Enforce readable table type and unbroken numeric tokens with suitable continuation/landscape layouts. | Raster/text-token checks on small/default/dense PDFs to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-033 | PR-09 | Planned | Correct/define the tendon-coordinate symbol and local sign/extreme convention. | Symbol/glossary consistency oracle to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-034 | PR-10 | Planned | Correct transverse torsion-steel citation to Formula (6.27). | Clause/formula reference snapshot to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-035 | PR-09 | Planned | Label Curve 2 user-defined and Curve 3 Eurocode design preset throughout UI/manual/report. | Cross-surface content matrix to be established in owning PR. | Pending | Pending | Pending | Pending | Curve selection is a direct user calculation choice; no project-basis adoption workflow applies. |
| F-036 | PR-09 | Planned | Add numerical algorithms/tolerances/failure states and a downloadable end-to-end worked example with hand pack. | Frozen independent oracle for all main report sections to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-037 | PR-10 | Planned | Rebuild table/equation vertical geometry to prevent glyph/rule and glyph/text collisions. | Measured-glyph raster preflight fixtures to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-038 | PR-11 | Planned | Add stable section-based equation IDs, numbers, source lines, and cross-references. | Unique-ID/reference-integrity checks to be established in owning PR. | Pending | Pending | Pending | Pending | Only governing/reused equations require numbering. |
| F-039 | PR-11 | Planned | Standardize equation blocks, substitutions, results/units, symbol definitions, and long-expression layout. | Symbol-definition and equation-layout checks to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-040 | PR-10 | Planned | Remove literal caret markup and normalize scientific notation, subscripts, powers, degrees, and units through one notation layer. | Text extraction and raster notation checks to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-041 | PR-11 | Planned | Add section-based Figure/Table numbering, captions, references, repeated units, and grayscale-safe plots. | Caption/reference and grayscale visual checks to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-042 | PR-11C | Implemented on branch; exact-head review pending | One immutable report/manual style identity plus structural and PDFium raster preflight; the report overview, Table 8.2 reference and furniture-only page are corrected, and the exact Kaleido server-mode `kopts` warning is suppressed only at image export. | Complete 60-page representative report and 46-page manual with exact A4/type/numeric/reference/body/furniture checks and tolerant approved-crop hashes. | `tests/test_publication_preflight.py`, retained publication/report/manual groups, `tests/test_report_rendered.py`, `tests/test_manual_rendered.py`, and preserved PDF/page-PNG outputs. | Pending exact candidate head | Pending | Pending | No solver/schema/trace change; compact renderer-scaled sub/superscripts remain below the ordinary `7.2 pt` table-type floor. |

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
