# Sector v0.92 QA closure ledger

This ledger is the implementation-side index for the sequential v0.92 closure
program. "Implemented" does not mean independently closed. A row becomes closed
only after GitHub CI, current-head Codex Review, and the original independent QA
reviewer all accept the same full commit SHA and that exact head is merged.

The ledger is updated in every owning PR. Pending rows deliberately do not claim
an oracle, regression, reviewed SHA, or closure that has not yet been produced.

| Finding | Owning PR | Implementation status | Calculation or presentation behavior | Independent oracle or benchmark | Regression tests and generated artifact evidence | Codex Review iterations / reviewed head | Independent adversarial closure SHA | Merged PR | Accepted residual limitation |
|---|---|---|---|---|---|---|---|---|---|
| F-001 | PR-01 | Closed and merged | One winding-independent, scale-aware topology gate now blocks malformed, non-finite, degenerate, repeated, backtracking, self-contacting/crossing, outside/touching/crossing-hole, overlapping, and nested-hole geometry in UI, project I/O, API, raw helpers, and solver entries. | Frozen `G-VALID-CONCAVE`, `G-INVALID-BOWTIE`, `G-INVALID-COLLINEAR`, `G-INVALID-HOLE-OUTSIDE`, and `G-INVALID-HOLE-OVERLAP` cases; test-only exact-rational segment/containment oracle. | `tests/test_geometry_topology.py`; `tests/fixtures/geometry_topology_f001.json`; focused Streamlit pre-solver smoke test; project v14 mixed-winding round trip; existing geometry, solver, shear, torsion, fatigue, capacity, and hand-calculation regressions; full local suite 1,399 passed and 1 skipped. | Three actionable comments on `0ae7e0a7cb2f2c904f3c44c46853db6ef93ac50e` were fixed; Codex Review accepted exact head `f3d609499af0d7c8fc9520e6131e81fcf72b19ef`. | `QA CLOSURE ACCEPTED — f3d609499af0d7c8fc9520e6131e81fcf72b19ef` | [PR #204](https://github.com/KasperLFabricius/Sector/pull/204); squash `91b2470e463a29c70e6cc6b08b123bcee84aa78d` | Exact terminal closure markers and forward intermediate collinear vertices remain valid; raw winding/order is preserved, terminal markers are removed from analysis copies, and analysis rings are oriented canonically. |
| F-002 | PR-02 | Closed and merged | Concrete compression and tension factors have distinct resolved values and provenance. `T_Rd,c` now uses `f_ctk,0.05 / gamma_ct`; the DK preset is `gamma_ct = 1.70 gamma0 gamma3`, while compressive `f_cd` continues to use the separately reported final concrete material input. Approved override values are retained separately from temporary preset values and restored after a mode transition. | Independent 300 x 600 mm C35 tube hand calculation: base EN `T_Rd,c = 29.96 kNm` (`gamma_ct = 1.50`) and DK/NA `T_Rd,c = 26.44 kNm` (`gamma_ct = 1.70`) at unity category factors; non-unity category and Eq. 6.31 governing-state transitions are also checked. | `tests/test_codes.py`; `tests/test_torsion.py::test_trd_c_hand_calculation_separates_base_en_and_dk_tension_factors`; category-factor, approved-override, method-switch, stale-state repair, report-derivation, project-round-trip, and Eq. 6.31 transition tests. | Eleven earlier actionable threads plus the later interrupted-project-load finding are resolved; Codex Review accepted exact head `c789ad9bfc94921f3383e9bce3c056b8e445cdcd`. | `QA CLOSURE ACCEPTED — c789ad9bfc94921f3383e9bce3c056b8e445cdcd` | [PR #205](https://github.com/KasperLFabricius/Sector/pull/205); squash `91bb63f9bd05050f508334202ca531367420062e` | No category is inferred. The selected edition remains a project design-basis decision. |
| F-003 | PR-03 | Implemented on branch; review and closure pending | The 2023 crack-control core now distinguishes mild reinforcement and prestressing steel, derives each contributing tendon’s `xi1` from `xi`, the largest effective mild-bar diameter and its own tendon diameter, and uses `(As,eff + sum(xi1 Ap))/Ac,eff`. Missing or invalid `xi` is blocking when a tendon contributes. | Standalone `tools/pr03_crack_oracle.py`; frozen `SLS-2023-XI1` expected `rho_p,eff = 0.014285714285714294` for `As = Ap = 1000 mm2`, `xi1 = 0.5`, `Ac,eff = 0.105 m2`; independent scalar direct-tension formulas. | `tests/test_crack_control_pr03.py`; mixed/prestress-only, bond, diameter, invalid-input, decompression, independent-oracle and provenance cases; 316 affected tests, 210 Streamlit tests and 1,489 full-suite tests passed on the pre-F-043 head; fresh live-source browser, 41-page report and 32-page manual evidence inspected. | Review of `4d8c09a13854dead91a10ac39ca352042c8a5d65` raised a P1 locked-in-prestress double subtraction and P2 global-diameter provenance issue; both were fixed. Codex Review later accepted `ab488e80906166e8edf02abc4d4fa800121fe8fc`, but the newly assigned F-043 scope makes that review obsolete; current-head review is pending. | Pending original reviewer. | Pending | No `xi` or edition applicability is inferred; the selectable 2023 method remains subject to the project design basis. |
| F-004 | PR-02 | Closed and merged | Danish fatigue presets resolve `gamma_s,fat = 1.20 x 1.10 x gamma0 x gamma3` and `gamma_c,fat = 1.45 x 1.10 x gamma0 x gamma3`; preset, approved-final override, and migrated legacy values have distinct persisted states and report derivations. Approved final overrides and their approval are retained outside preset widget state; rejected stale values remain blocked until an enabled edit or explicit confirmation repairs them. | At unity category factors, `gamma_s,fat = 1.32` and `gamma_c,fat = 1.595`; all three edition selections, non-unity categories, override persistence, and legacy blocking are independently asserted. | `tests/test_fatigue_inputs.py`; `tests/test_fatigue_analysis.py`; `tests/test_project_io.py`; Streamlit switching/reload and stale live/durable repair tests in `tests/test_app_smoke.py`; PDF evidence in `tests/test_report.py`. | Eleven earlier actionable threads plus the later interrupted-project-load finding are resolved; Codex Review accepted exact head `c789ad9bfc94921f3383e9bce3c056b8e445cdcd`. | `QA CLOSURE ACCEPTED — c789ad9bfc94921f3383e9bce3c056b8e445cdcd` | [PR #205](https://github.com/KasperLFabricius/Sector/pull/205); squash `91bb63f9bd05050f508334202ca531367420062e` | Old saved numeric factors are retained but require an explicit preset-or-approved-override decision before a fatigue verdict. |
| F-005 | PR-04 | Planned | Add distinct DS/EN 1992-2:2005 + AC:2008 methodology with explicit inheritance, bridge overrides, applicability, and non-pass unsupported states. | To be established in owning PR from the four-layer standards comparison and independent bridge examples. | Pending | Pending | Pending | Pending | None accepted. |
| F-006 | PR-05 | Planned | Add distinct DS/EN 1992-2 + DK/NA:2015 methodology and Danish bridge choices. | To be established in owning PR for road, footbridge, and railway cases. | Pending | Pending | Pending | Pending | None accepted. |
| F-007 | PR-03 | Implemented on branch; review and closure pending | EN 1992-1-1:2023 uniform direct tension is calculated for a validated solid rectangle with reinforcement on opposed faces using the Figure 9.3 perimeter area, `kfl = 1`, `k1/r = 1`, and no bending cap. Every cracked unsupported or incomplete state now has an explicit blocking disposition; a partial numerical set cannot produce overall PASS. | Standalone rectangular perimeter-area, reinforcement-ratio, strain, spacing and crack-width oracle in `tools/pr03_crack_oracle.py`. | Pure tension, good/poor bond, zero/near-zero curvature, all-tension transition, unsupported geometry, 2005 direct-tension gate, zero reinforcement, decompression, SLS status precedence and app integration tests. | Pending current-head review. | Pending original reviewer. | Pending | 2005 direct tension and non-rectangular/combined all-tension inputs remain explicitly `NOT ASSESSED`; they cannot yield PASS. |
| F-008 | PR-03 | Implemented on branch; review and closure pending | The engine records dominant direction/scope, while UI result panels, Results Overview, the saved design-basis limitation, manual, and report result/conclusion state that orthogonal or inclined crack systems are not assessed. | Rotation oracle compares an asymmetric section and reinforcement after rigid rotations while independently transforming loads and preserving crack width. | Rotated asymmetric engine cases plus app summary, report text/raster and manual content gates. | Pending current-head review. | Pending original reviewer. | Pending | Directional limitation remains explicit until PR-06 supplies an applicable opt-in multidirectional method. |
| F-009 | PR-06 | Planned | Keep independent `Vx`/`Vy` results but prevent combined PASS without a selected applicable interaction method. | To be established in owning PR for uniaxial limits, balanced biaxial load, axis swap, rotation, and interaction boundary. | Pending | Pending | Pending | Pending | No universal interaction rule will be inferred. |
| F-010 | PR-04 | Planned | Route bridge concrete-fatigue equations only through bridge methodology or explicit warned project-basis adoption. | To be established in owning PR from bridge provisions and independent examples. | Pending | Pending | Pending | Pending | None accepted. |
| F-011 | PR-07 | Planned | Add report design scope, assumptions/exclusions, overall conclusion, and action register for every non-pass state. | To be established in owning PR through structural report assertions. | Pending | Pending | Pending | Pending | None accepted. |
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
| F-022 | PR-05 | Planned | Add explicit infrastructure-manager/project-basis fields with mapped-rule calculation effects and provenance. | Authority-routing decision table and round-trip examples to be established in owning PR. | Pending | Pending | Pending | Pending | Unmapped authority choices warn and cannot silently change calculations. |
| F-023 | PR-06 | Planned | Add separate opt-in, sourced biaxial crack/shear interaction options with domain and fallback state. | Independent limiting, symmetry, rotation, and unsupported-domain benchmarks to be established in owning PR. | Pending | Pending | Pending | Pending | No universal interaction rule will be invented. |
| F-024 | PR-07 | Planned | Add amendment history, sign-off, action ownership, and closure state to reports. | Blank/partial/full governance report fixtures to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-025 | PR-12 | Planned | Prevent whole Inputs-workspace rebuild/stall on ordinary pane changes. | Browser rerun/time-to-idle telemetry to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-026 | PR-12 | Planned | Render only the active input pane while retaining unmounted values in one canonical draft model. | Zero-lost-edit and inactive-payload browser evidence to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-027 | PR-12 | Planned | Use safe fragment-scoped reruns and batching/commit boundaries for active panes. | Rapid-switch, rerun-count, and latest-state calculation/autosave evidence to be established in owning PR. | Pending | Pending | Pending | Pending | Shared state writes will not be parallelized. |
| F-028 | PR-12 | Planned | Add opt-in phase telemetry and browser performance budgets. | Cold/warm p50/p95/max, delta-size, long-task, and rerun benchmark to be established in owning PR. | Pending | Pending | Pending | Pending | Only immutable/static resources may receive broad caching. |
| F-029 | PR-07 | Planned | Use one authoritative build-information record across filenames, PDFs, project JSON, cover/footer, report, and manual. | One generated project/report/manual identity comparison to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-030 | PR-08 | Planned | Print applied-ray plastic-utilization bracket vertices, interpolation, intersection, scale, tolerance, and correct sample label. | Between-sweep-angle independent reconstruction fixture to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-031 | PR-08 | Planned | Print complete TOTAL/LONG/DIF/RST1 creep decomposition, material strain planes, contributions, residuals, and iterations. | Independent resultant/stress reconstruction to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-032 | PR-10 | Planned | Enforce readable table type and unbroken numeric tokens with suitable continuation/landscape layouts. | Raster/text-token checks on small/default/dense PDFs to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-033 | PR-09 | Planned | Correct/define the tendon-coordinate symbol and local sign/extreme convention. | Symbol/glossary consistency oracle to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-034 | PR-10 | Planned | Correct transverse torsion-steel citation to Formula (6.27). | Clause/formula reference snapshot to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-035 | PR-09 | Planned | Label Curve 2 legacy/user-defined and Curve 3 Eurocode design preset throughout UI/manual/report. | Cross-surface content matrix to be established in owning PR. | Pending | Pending | Pending | Pending | Project-basis adoption of Curve 2 must be explicit. |
| F-036 | PR-09 | Planned | Add numerical algorithms/tolerances/failure states and a downloadable end-to-end worked example with hand pack. | Frozen independent oracle for all main report sections to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-037 | PR-10 | Planned | Rebuild table/equation vertical geometry to prevent glyph/rule and glyph/text collisions. | Measured-glyph raster preflight fixtures to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-038 | PR-11 | Planned | Add stable section-based equation IDs, numbers, source lines, and cross-references. | Unique-ID/reference-integrity checks to be established in owning PR. | Pending | Pending | Pending | Pending | Only governing/reused equations require numbering. |
| F-039 | PR-11 | Planned | Standardize equation blocks, substitutions, results/units, symbol definitions, and long-expression layout. | Symbol-definition and equation-layout checks to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-040 | PR-10 | Planned | Remove literal caret markup and normalize scientific notation, subscripts, powers, degrees, and units through one notation layer. | Text extraction and raster notation checks to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-041 | PR-11 | Planned | Add section-based Figure/Table numbering, captions, references, repeated units, and grayscale-safe plots. | Caption/reference and grayscale visual checks to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-042 | PR-11 | Planned | Add a shared publication style system plus structural and raster PDF preflight. | Complete manual and representative report preflight/crop regression to be established in owning PR. | Pending | Pending | Pending | Pending | None accepted. |
| F-043 | PR-03 core; PR-04/PR-05 inherit or override | Implemented on PR-03 branch; exact-head review and closure pending | Response duration and SLS-combination class are independent structured fields. Standard appearance, durability and decompression criteria route only to the edition/member-specific required combination; project criteria require explicit per-combination limits and source. Missing, legacy or duplicate-independent mappings return `NOT ASSESSED / REVIEW`; unrelated calculated responses remain informational. Crack-history selection remains independent. | Frozen ordinary-member reproducer: QP `w_k = 0.22 mm` versus characteristic total `0.31 mm` at `w_lim = 0.30 mm` gives QP PASS. Separate bonded-prestress frequent/QP-decompression, 2023 Table 9.1/Table 9.2, missing/ambiguous mapping and project-criterion cases. Controlled local evidence only: 2004 §7.3.1(5)/Table 7.1N; DK NA:2024 §7.3.1(5)/Table 7.1 NA; 2023 §9.2.1(6)/Tables 9.1–9.2. | `tests/test_sls.py`, `tests/test_load_cases.py`, `tests/test_case_analysis.py`, `tests/test_project_io.py`, selected `tests/test_app_smoke.py`, report/manual text and rendered-artifact tests. Final affected gate: 279 passed with 32 expected Kaleido warnings. Fresh 41-page report pages 30–31 show QP `0.213 mm` PASS and total/characteristic `0.310 mm` informational; fresh 33-page manual pages 22–23 document routing and fail-closed migration. | Prior clean review of `ab488e80906166e8edf02abc4d4fa800121fe8fc` predates F-043 and is not a closure gate for the new head. Exact-head Codex Review pending. | Pending original reviewer on the new exact head. | Pending | PR-04 must add EN 1992-2 bridge-base routing and PR-05 the Danish bridge matrix, including the DK non-prestressed frequent-column route; neither may fall back to a generic maximum. The current solver leaves required bonded-prestress decompression `NOT ASSESSED` unless its concrete-stress evidence is available. |

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
- Exact reviewed implementation head:
  `f3d609499af0d7c8fc9520e6131e81fcf72b19ef`.
- GitHub CI run 170, current-head Codex Review, and the original independent QA
  reviewer all accepted that exact SHA.
- Independent closure statement:
  `QA CLOSURE ACCEPTED — f3d609499af0d7c8fc9520e6131e81fcf72b19ef`.
- [PR #204](https://github.com/KasperLFabricius/Sector/pull/204) was squash
  merged as `91b2470e463a29c70e6cc6b08b123bcee84aa78d`.

## PR-02 evidence log

- Scope: F-002 and F-004 only.
- Primary Danish source: `DS/EN 1992-1-1 DK NA:2024`, revision
  2024-02-01, pages 8-9. Table 2.1Na NA gives the general reinforced-concrete
  compression, concrete-tension, and reinforcement bases as
  `1.45 gamma0 gamma3`, `1.70 gamma0 gamma3`, and
  `1.20 gamma0 gamma3`. The following fatigue paragraph applies a further 1.1
  multiplier to the concrete and reinforcement fatigue factors.
- Source verification: the locally controlled Design Basis copy was checked
  by text extraction and page raster review. No normative wording was sourced
  from the reviewed output PDFs or from an undocumented combined standard/NA
  branch.
- Applicability qualification: Sector reports the selected method and provision
  but does not infer that this edition is applicable to a particular project;
  that decision remains with the project design basis.
- F-002 oracle: for the documented 300 x 600 mm C35 solid rectangle,
  `A_k = 0.100 m2`, `t_ef = 100 mm`, and
  `f_ctk,0.05 = 0.7 f_ctm`; the independent base-EN and DK results are
  29.96 kNm and 26.44 kNm. A demand between the corresponding Eq. 6.31
  boundaries passes under base EN and fails under the DK tensile factor.
- F-004 oracle: unity category factors give
  `gamma_s,fat = 1.20 x 1.10 = 1.32` and
  `gamma_c,fat = 1.45 x 1.10 = 1.595`. Tests also use non-unity
  `gamma0 = 0.95`, `gamma3 = 1.10`.
- Supplied-project migration evidence: the reviewed v14
  `sector_section.json` retains its saved 1.15/1.50 fatigue values as
  `Legacy saved factors - review required`, while its Danish torsion method
  migrates to the edition-derived `gamma_ct = 1.70` preset. No source project
  file was modified.
- Focused validation before immutable-head review: 137 pure factor, capacity,
  fatigue-analysis, and project-I/O tests passed; 11 targeted Streamlit and PDF
  tests passed; the final compatibility/manual/fixture correction set passed
  its three focused regressions.
- Complete local suite: 1,432 passed with 32 known Kaleido warnings in
  558.40 s using four fixed workers; version remained exactly `0.91`.
- Fresh generated artifacts: the computed report fixture rendered 41 pages and
  the manual rendered 31 pages. Their structural/raster preflights passed, and
  the input-settings, torsion-factor, material-factor-basis, fatigue-basis,
  manual UI-guidance, Danish fatigue-equation, and worked-torsion pages were
  visually inspected.
- Exact head `930a13ac7b0bc48656fe1f16065d130768ef94be` passed 1,462
  local tests, GitHub Sector QA run 184, a 41-page report and 31-page manual
  build, reproducible Windows packaging without executing the binary, and a
  clean current-head Codex Review with all 11 review threads resolved.
- The original independent reviewer rejected that head after reproducing a
  stale live/durable category-factor repair path that temporarily selected a
  preset and silently replaced approved final fatigue and torsion factors under
  their old approval references.
- The remediation keeps approved override values and approvals outside preset
  widget state, restores them on return to override (or clears a first
  unapproved override), enables every rejected factor field for direct repair,
  and provides an explicit confirmation path when a browser reconstructs the
  same displayed positive value. The regression exercises enabled UI events,
  stale live and durable mirrors, the former preset-transition path,
  calculation, project download, and round-trippable autosave.
- Exact head `6b647123fbc066310883d13802a0a564f78127ff` passed 1,463 local
  tests, GitHub Sector QA run 185, fresh report/manual generation, and
  reproducible Windows packaging without executing the binary. Codex Review
  then identified one P1 interrupted-load path: a rapid Analysis navigation
  could expose the prior project's `_latest_inputs` after the new project's
  live and durable state had already been installed.
- The review remediation invalidates `_latest_inputs` as part of every valid
  whole-project replacement. A focused AppTest reproduces a superseded Inputs
  build, proves Analysis has no Calculate action until a complete new Inputs
  build commits, and then verifies the rebuilt payload belongs to the loaded
  project.
- Exact head `c789ad9bfc94921f3383e9bce3c056b8e445cdcd` passed the
  immutable-head local and GitHub CI gates. Codex Review found no remaining
  actionable issue on that head, and the original reviewer returned
  `QA CLOSURE ACCEPTED — c789ad9bfc94921f3383e9bce3c056b8e445cdcd`.
- [PR #205](https://github.com/KasperLFabricius/Sector/pull/205) was squash
  merged as `91bb63f9bd05050f508334202ca531367420062e`.

## PR-03 evidence log

- Scope: F-003, F-007, F-008 and F-043 only.
- Local source: `DS/EN 1992-1-1:2023`, clauses 9.2.2(3) and 9.2.3,
  Formulas (9.6), (9.8), (9.11), (9.12), (9.15), (9.18) and (9.20),
  Figure 9.3, Table 10.1 and Annex G.5. The local copy is catalogued as
  published but not implemented; Sector therefore presents it as an explicit
  selectable edition and does not claim that it is the current Danish project
  basis. No internet standards source was used.
- 2023 mixed-reinforcement route:
  `rho_p,eff = (As,eff + sum(xi1 Ap)) / Ac,eff`, with
  `xi1 = sqrt(xi phi_s / phi_p)` for mixed reinforcement and `xi1 = xi`
  when prestressing steel alone controls cracking. Each tendon retains its
  table diameter and typed provenance; a missing/non-finite/out-of-range `xi`
  blocks the affected result.
- Direct-tension route: the validated solid-rectangle perimeter-area branch
  follows Figure 9.3 and uses `kfl = 1.00`, `k1/r = 1.00`, and no bending
  `(h-x)` cap. Unsupported 2005 direct tension, non-rectangular uniform
  tension, combined all-tension transition states, and incomplete inputs are
  explicit `NOT ASSESSED` dispositions.
- F-043 combination-routing basis was checked only against controlled local
  standards: DS/EN 1992-1-1:2004 section 7.3.1(5), Table 7.1N;
  DS/EN 1992-1-1 DK NA:2024 section 7.3.1(5), Table 7.1 NA; and
  DS/EN 1992-1-1:2023 section 9.2.1(6), Tables 9.1 and 9.2. Response duration
  remains solver provenance, while Characteristic, Frequent and
  Quasi-permanent are explicit load-table fields. Ordinary reinforced/unbonded
  durability routes to Quasi-permanent; bonded durability routes to Frequent;
  2023 appearance routes separately to Quasi-permanent; and any applicable
  bonded decompression route remains a separate Quasi-permanent criterion.
- Project-defined crack criteria require an approved source and a separate
  positive limit for every applicable combination. Pre-v17 files, malformed
  current routing tokens, absent required combinations, or duplicate independent
  mappings cannot infer PASS or a standard failure. Structured inputs and a
  compact hash-bound audit snapshot round-trip through save/load, session state
  and autosave; loaded snapshots are never restored as live solver results.
- Independent oracle: `tools/pr03_crack_oracle.py` imports no Sector
  calculation code. It reproduces Formula (9.6), Formula (9.12), the
  rectangular direct-tension perimeter area, and the 2023 scalar crack-width
  chain. Frozen benchmark `SLS-2023-XI1` expects
  `rho_p,eff = 0.014285714285714294`.
- Post-review local gates are green: the three exact review regressions,
  21 focused PR03 tests, 316 affected
  serviceability/project/report/manual tests (including rendered-document
  checks and the three affected AppTests), 210 Streamlit AppTests, and the
  complete four-worker suite of 1,489 tests. The full suite completed in
  718.59 s with the expected 32 Kaleido warnings and no failures.
- The lean F-043 affected gate completed in 189.59 s: 277 tests passed before
  two stale report text-contract assertions were repaired, and both repaired
  tests then passed, for 279 affected checks green in total. This gate covers
  core routing, the independent reproducer, load-table mapping, project/session/
  autosave persistence, headless fail-closed behavior, selected Streamlit paths,
  report/manual content, and real rendered-artifact preflight. The complete suite
  remains delegated to GitHub CI under the lean-QC policy.
- Fresh generated evidence passed structural and raster preflight:
  `sector-report-reference.pdf` (41 pages; conclusion limitation on page 1,
  routed acceptance/provenance on page 30, and QP `0.213 mm` versus
  informational total `0.310 mm` on page 31) and
  `sector-manual-reference.pdf` (33 pages; duration/combination separation and
  2004/2023 routing on pages 22-23). A fresh source-tree browser walkthrough on
  `Sector v0.91` retained the edited Elastic crack-width checkbox without the
  former data-editor session-state exception, enabled the 2023 tendon-bond
  and `xi` inputs, and displayed the one-directional limitation. No image
  from another executable or build was substituted.
- Version remains exactly `0.91`. F-020 and unrelated local build,
  quarantine and test-temp directories remain untouched.
- The first Codex Review on
  `4d8c09a13854dead91a10ac39ca352042c8a5d65` found a P1 double subtraction
  of locked-in prestress from the already-passive long-term tendon stress and
  a P2 incorrect per-tendon diameter-source claim when the global override was
  active. Both are remediated with nonzero-prestrain and override-provenance
  regressions. Codex Review subsequently accepted
  `ab488e80906166e8edf02abc4d4fa800121fe8fc`, but the later independent F-043
  finding invalidated that closure gate. New exact-head Codex Review, GitHub CI,
  original independent QA closure and merge remain pending; this implementation
  log does not self-certify closure.
