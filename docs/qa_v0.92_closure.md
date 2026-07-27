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
| F-043 | PR-03 core; PR-04/PR-05 inherit or override | Latest independent-QA and exact-review remediations implemented locally on the PR-03 branch; new exact-head gates pending | Response duration and SLS-combination class are independent. Standard-derived width, decompression and appearance criteria route only to the combination required for the selected edition and member/protection/exposure class. Missing, migrated, malformed or duplicate mappings remain `NOT ASSESSED / REVIEW`; unrelated valid responses are informational and crack history remains separate. Every non-null calculated response is validated before criterion routing. Raw decompression acceptance requires complete typed and mutually consistent status, finite concrete-stress value, usable governing location and solver provenance across every matched response label sharing the routed state; non-finite audit fields are rejected and publication repeats that completeness check. A definite `EXCEEDED` criterion governs the top-level `FAIL` over a separate incomplete criterion, while every `NOT ASSESSED` detail remains reported. Publication independently cross-checks current responses at calculation-record, project save/load/provenance, autosave and report boundaries. Every accepted top-level and criterion item must state a valid required combination, structured applicability/source and one explicit current response identity. Width publication recomputes the maximum, utilization and margin across every matched response and correlates the governing case/element. Decompression publication correlates status, numeric value, governing location, response-context provenance and solver provenance for every matched response, not only the stored case. The report overlays current visible values on their canonical response identities, preserves matched DK fine/coarse responses as criterion inputs and uses MPa for decompression. A rejected, missing, changed or differently named response invalidates stale PASS/FAIL evidence, while legitimate solver `NOT APPLICABLE` nulls remain non-rejections. | Frozen 2004 ordinary-member reproducer: QP `w_k = 0.22 mm` versus characteristic total `0.31 mm` at `w_lim = 0.30 mm` gives QP PASS. Frozen 2023 bonded PL2/3 reproducer: QP `0.31 mm` versus unrelated Frequent `0.22 mm` at `0.30 mm` gives QP FAIL. Separate Table 9.1 appearance, Table 9.2 protection/exposure and decompression routes are covered. Adversarial evidence includes Boolean/scientific containers, one-shot iterables, malformed/non-mapping responses, scalar/mapping `matched_responses`, empty/malformed/duplicate table scopes, missing or mismatched response identities/combinations, changed or differently named governing responses, incomplete/missing/conflicting/non-finite matched decompression evidence, a known width failure beside unavailable decompression, interrupted event reconstruction, and intentionally inconsistent PASS snapshots through project/session/autosave/report/headless paths. Controlled local evidence: 2004 section 7.3.1(5)/Table 7.1N; DK NA:2024 section 7.3.1(5)/Table 7.1 NA; 2023 section 9.2.1(6)/Tables 9.1-9.2. | Cumulative lean evidence is 443 unique affected checks. The consolidated architecture gate passes 227 core SLS/source-policy nodes plus ten boundary/application nodes. Earlier complete Streamlit, report/manual and rendered-artifact gates remain green and are not duplicated under the lean-QC policy; new exact-head CI is required. | Review of `855caff3c0355ba30c6b114ae909d53578087d0a` found all-matched-width and full-decompression gaps. Review of `5b9a8bc528af9b34818b6b06e5dd1d1bf22bda59` then found that acceptance could omit its required combination and that full decompression comparison still covered only one matched response. Review of `add0713c468d77ddfe38f6a022d2825ee3545d6d` found that raw decompression acceptance still selected the first matched label and that report publication unconditionally demoted matched coarse responses. Review of `c76677d0b5f18cf0baa99877cba91056ec41bfe4` found incomplete single-response decompression evidence and known-failure precedence gaps. Review of `2352d3bfc3316f10cce07e6850b91df1d7d65501` found non-finite governing/provenance evidence acceptance. Review of `fe5cf369127bd1f2ebdaa1b8da320f6e67d4fe88` found scalar matched-response evidence could reach aggregate rebuilding. All are locally remediated and consolidated; a new exact-head Codex Review remains required after push. | Original reviewer rejected `ef9045071a49442e2f53fa1f7da81096aa9f3a18` because malformed current responses could coexist with a persisted or reported PASS. Exact-head resubmission is pending after CI and Codex Review. | Pending | PR-04 must add EN 1992-2 bridge-base routing and PR-05 the Danish bridge matrix, including the DK non-prestressed frequent-column route; neither may fall back to a generic maximum. Required decompression remains `NOT ASSESSED` unless complete concrete-stress evidence exists. |

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
  Quasi-permanent are explicit load-table fields. The 2004 ordinary/unbonded
  route is Quasi-permanent, while 2004 bonded width is Frequent and applicable
  decompression is separately Quasi-permanent. The 2023 route additionally
  records a controlled Table 9.2 exposure group and, for bonded tendons, the
  Protection Level 1/pretensioned versus Protection Levels 2/3 group. PL2/3
  shares the reinforced/unbonded Quasi-permanent width branch. PL1/pretensioned
  uses Frequent width for X0/XC1 and XC2-XC4, Quasi-permanent decompression for
  XC2-XC4, and Frequent decompression for XD/XS and XF. Appearance remains a
  separate Quasi-permanent Table 9.1 criterion.
- Project-defined crack criteria require an approved source and a separate
  positive limit for every applicable combination. Pre-v17 duration-only files,
  v17 2023 files without the new structured route, malformed current
  routing tokens, absent required combinations, or duplicate independent
  mappings cannot infer PASS or a standard failure. Structured inputs and a
  compact hash-bound audit snapshot round-trip through save/load, session state
  and autosave; loaded snapshots are never restored as live solver results.
- Python and NumPy Boolean values are rejected before conversion for `xi` and
  every crack/SLS numeric criterion at core, project parse/dump/provenance,
  live/durable session, autosave/download and report boundaries. Reconstructed
  session defaults cannot clear the rejection marker; a real edit or explicit
  confirmation is required, and the result remains `NOT ASSESSED / REVIEW`.
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
- Exact-head review of `2a095acc932b242c2465fac0c1b0d1ddfc59c102`
  found that duplicate required-combination designations were rejected within
  one Elastic row but not across independently checked rows. The remediation
  constructs one table-wide mapping scope with case-qualified response IDs,
  routes that scope into every crack assessment, and includes the scope in the
  Elastic-row cache token so an applicability change cannot preserve a stale
  PASS. Core, orchestration/cache, and real multi-case AppTest regressions all
  fail closed with mapping provenance; the focused 30-test matrix passed.
- GitHub Sector QA run `30263675408` then completed the full calculation and
  artifact work: 1,512 tests passed, one skipped, 32 expected Kaleido warnings,
  and both the 41-page report and 33-page manual rendered. Its only two failures
  were stale UI-contract assertions that still expected the pre-F-043 generic
  crack-limit label and the Elastic table without its two explicit combination
  columns. Those assertions now describe the intentional interface, and their
  exact two-test rerun passed; the new exact-head CI rerun remains a closure gate.
- Original independent QA rejected
  `bae40bf3f671c4eac994ded66481354ec86137b1`: its 2023 bonded route collapsed
  both Table 9.2 protection groups into Frequent width/QP decompression, and
  Python/NumPy Booleans could become favourable numeric `1.0` values. Schema
  v18 now records the exposure/protection matrix and fails closed on ambiguous
  v17 migration. Boolean `xi` and crack/SLS limits are rejected before coercion
  through every persistence, calculation and publication boundary. The latest
  lean remediation gate had 322 unique affected checks green, including cache,
  AppTest, report and rendered-manual evidence; exact-head external gates remain
  pending.
- Codex Review of
  `65d730011691a6a05f99df91090746f469224be8` then found two further P1
  fail-closed gaps. An invalid pending event could be sanitized to `0.0` and,
  after an interrupted rerun, be mistaken for a repair; and direct
  `run_analysis`/stress-assessment callers could still consume Boolean `fctm`
  or stress limits when crack-width routing was disabled. Invalid or stale
  pending entries are now removed whenever any copy of that key is rejected,
  while only a matching genuine event/confirmation can clear the marker.
  Public analysis, single-case analysis, upper-limit and stress-assessment
  boundaries reject Python and NumPy Booleans before any solver or result
  conversion. The cumulative lean evidence is now 342 unique affected checks;
  the newest exact-review and bounded affected gates passed 32, 2 and 154
  checks respectively.
- Codex Review of
  `02120ed094dfe22509dafa336d6416e065faaa82` then found one P2 iterable
  coverage gap: NumPy object arrays and pandas Series were iterable but not
  `Sequence` instances, so a contained Boolean could still reach
  `float(True)`. Boolean inspection now covers pandas containers, NumPy
  object/zero-dimensional arrays, mappings and finite iterables. A one-shot
  stress iterator is materialized exactly once so validation does not consume
  the solver input. Seven focused negative/control cases and the complete
  158-check SLS/source-policy gate pass, bringing cumulative unique affected
  evidence to 349 checks.
- Original independent QA of
  `2f32782b3d69262742d59dfaac9a38d49ef18bf6` then found two remaining result
  boundary gaps. Boolean-bearing calculated `w_k` values were ranked through
  `float()` and could produce a false PASS at `0.0`; and a mapping or a custom
  non-`Iterator` one-shot stress iterable could respectively coerce a Boolean
  key or be consumed before calculation. Calculated crack widths are now
  required to be finite, non-negative, non-Boolean numerics before ranking.
  Rejected widths produce `NOT ASSESSED / REVIEW`, and report/calculation-record
  publication cannot retain a PASS or invalid Boolean width. Stress mappings
  are rejected, while every accepted ordered iterable is materialized once
  before inspection and calculation. Ten focused regressions, 166 complete
  SLS/source-policy checks, 44 crack report/project checks and two application
  routing/record checks pass, bringing cumulative unique affected evidence to
  359 checks.
- Codex Review of
  `bc6ce9e9020fa33d8c8e9c02edbc94b313328668` found that calculated-width
  validation still began after combination matching. A valid QP response could
  therefore produce an overall PASS while a malformed characteristic response
  remained informational. Every non-null calculated response is now validated
  before criterion routing. A separate result-integrity criterion blocks the
  overall verdict and records response/solver provenance, while the valid QP
  response remains the only input to its standard-derived criterion. The report
  prints the rejection note even when another response has a valid width. Five
  focused regressions, 169 complete SLS/source-policy checks, 44 crack
  report/project checks and two application contracts pass, bringing cumulative
  unique affected evidence to 362 checks.
- Codex Review of
  `ac195dead08a4cb807267ca8f3f23092afd09fec` found that a truthy non-mapping
  response assigned to a decompression combination was rejected globally but
  could still reach `.get("decompression")` and raise. Rejected candidates now
  short-circuit every criterion before specialized routing. The exact regression
  and complete 170-check SLS/source-policy gate pass, bringing cumulative unique
  affected evidence to 363 checks.
- Codex Review of
  `ef6896a389498ad61b8813a0335577a70ec54633` found that the calculation-record
  boundary still called `.get("wk")` on the same truthy non-mapping response.
  Publication now rejects a non-mapping response before reading any fields,
  retains `NOT ASSESSED / REVIEW` and solver provenance, and records no numeric
  acceptance evidence. The exact regression and 106-check application/
  source-policy slice pass, bringing cumulative unique affected evidence to
  364 checks.
- Original independent QA then rejected
  `ef9045071a49442e2f53fa1f7da81096aa9f3a18`: a calculation record or report
  could combine a malformed current response with a stale `OK / PASS`
  assessment and publish the old verdict. One shared publication sanitizer now
  revalidates current response evidence at calculation-record, project
  dump/load/provenance, autosave and report boundaries. Any rejected response
  forces `NOT ASSESSED / REVIEW`, clears top-level and criterion
  values/utilization/margins, and retains the rejection and solver provenance.
  Intentionally inconsistent PASS snapshots now fail closed through direct
  calculation records, save/load, loaded audit snapshots, autosave and PDF
  report generation. Six focused regressions, 45 crack report/project checks
  and 107 app/source-policy checks pass, bringing cumulative unique affected
  evidence to 365 checks.
- Codex Review of
  `0729cb8a641b860e0dec16de01ada39f60ff193a` found two remaining publication
  correlations. First, any finite criterion-input response could support a
  stale PASS/FAIL even when its name differed from the governing response or
  its current width no longer matched the stored acceptance value. Second, the
  report classified legitimate solver `NOT APPLICABLE` null crack responses as
  malformed. Publication now correlates every accepted top-level/criterion
  item with the current governing identity and matching width or decompression
  evidence. Missing, differently named or changed evidence fails closed with a
  detailed reason, while a null carrying an explicit `NOT APPLICABLE`
  disposition remains valid. Matching decompression evidence is retained in
  the audit record and remains publishable. Nine focused regressions, 45 crack
  report/project checks and 109 app/source-policy checks pass, bringing
  cumulative unique affected evidence to 369 checks.
- Codex Review of
  `855caff3c0355ba30c6b114ae909d53578087d0a` found that an accepted
  multi-response criterion checked only its stored `case`, so a different
  matched fine/coarse response could grow and leave stale acceptance evidence.
  It also found that decompression correlation compared status but not the
  numeric value or governing location. Publication now combines the stored
  case with every `matched_responses` entry, requires one explicit current
  response identity and required combination, recomputes the maximum across
  all matched widths, and checks the governing case and element. Decompression
  additionally correlates status, finite numeric value, governing location and
  solver provenance. Matching decompression and real DK fine/coarse
  acceptance/failure controls remain publishable. Twelve focused regressions,
  46 crack report/project checks, 111 app/source-policy checks and the real DK
  control pass, bringing cumulative unique affected evidence to 372 checks.
- Codex Review of
  `5b9a8bc528af9b34818b6b06e5dd1d1bf22bda59` found that a malformed
  accepted item could omit `required_combination`, bypassing both the
  combination and response-identity checks. It also found that a
  multi-response decompression criterion fully correlated only the stored
  governing response. Every accepted item must now state a valid
  Characteristic, Frequent or Quasi-permanent combination; missing/invalid
  values fail closed before publication. Full decompression status, value,
  location and solver provenance are compared for every matched response.
  Regressions preserve valid structured round trips and matching
  decompression while rejecting the missing-combination and changed
  non-governing decompression cases. Twelve focused regressions, 47 crack
  report/project checks and 112 app/source-policy checks pass, bringing
  cumulative unique affected evidence to 374 checks.
- Codex Review of
  `add0713c468d77ddfe38f6a022d2825ee3545d6d` found that the raw
  decompression criterion still selected the first matched response label,
  allowing a conflicting or missing DK fine/coarse alias to coexist with an
  on-screen PASS. It also found that report publication marked every
  coarse-named response informational even when that response was explicitly
  matched to the criterion. Raw assessment now requires complete and
  consistent decompression status, value, governing location and solver
  provenance across all labels sharing the response identity. Report
  publication overlays visible results on their canonical fine/coarse names,
  preserves their criterion roles, and retains the governing element identity.
  Six focused regressions, 173 core SLS/source-policy checks, 47 crack
  report/project checks and three directly affected application checks pass.
  The four new independent regression nodes bring cumulative unique affected
  evidence to 378 checks.
- Codex Review of
  `c76677d0b5f18cf0baa99877cba91056ec41bfe4` found that a single
  matched decompression response could still claim `OK` with status alone, or
  with a Boolean stress value, missing governing location or absent solver
  provenance. It also found that a separate incomplete criterion took
  top-level precedence over a known width failure. Raw and publication
  boundaries now require complete typed decompression evidence for every
  accepted response. `EXCEEDED` now governs overall `FAIL` over
  `NOT ASSESSED`, while the incomplete criterion remains explicit in the
  detailed results. Twelve focused regression cases, 178 core
  SLS/source-policy checks, 47 crack report/project checks and six directly
  affected application checks pass. The six new independent regression nodes
  bring cumulative unique affected evidence to 384 checks.
- Codex Review of
  `2352d3bfc3316f10cce07e6850b91df1d7d65501` found that non-finite
  scalar governing-location or solver-provenance values still counted as
  populated audit evidence. The shared raw/publication predicate now accepts a
  lengthless scalar only when it is finite, so `NaN` and `Inf` fail closed.
  Ten focused regressions, 180 core SLS/source-policy checks, 47 crack
  report/project checks and six directly affected application checks pass. The
  three new raw/publication regression nodes bring cumulative unique affected
  evidence to 387 checks.

### F-043 consolidated invariant audit

Scope was frozen after the two `c76677d` P1 remediations. Before another push,
full CI or Codex Review, the raw-assessment and publication paths were audited
as one state model:

| Invariant family | Accepted state | Blocking state and retained evidence |
| --- | --- | --- |
| Required response count | Exactly one explicit response identity; consistent fine/coarse aliases may share it. | Zero matches, multiple independent identities, duplicated table identities or an empty/malformed table scope give `NOT ASSESSED / REVIEW`. |
| Identity and combination | Current response identity and required combination agree with the table-wide mapping scope. | Missing/stale identity, missing required combination, scope mismatch or a conflicting alias combination blocks routing without inferring from duration. |
| Alias context | All labels sharing an identity agree on combination, duration, mapping provenance and solver provenance. | Any conflicting field blocks the whole routed criterion; no alias is silently demoted to informational. |
| Decompression evidence | `OK`/`EXCEEDED` carries typed status, finite signed MPa value, governing concrete location and solver provenance consistent with the response context and every alias. A solver-proven `NOT APPLICABLE` may omit value/location. | Missing, Boolean, non-scalar, non-finite, changed or conflicting status/value/location/provenance gives `NOT ASSESSED / REVIEW`; nested `NaN`/`Inf` cannot cross publication. |
| Response role | Every current response mapped to the required combination is a criterion input; explicitly different combinations remain informational. | A required alias marked informational, a hidden/new required response or an unaccounted independent response invalidates stored PASS/FAIL evidence. |
| Aggregate precedence | `INVALID` > `EXCEEDED` > `NOT ASSESSED` > `OK` > `NOT APPLICABLE`; a known exceedance remains FAIL while incomplete criteria remain visible. | Published top-level status, value, limit, utilization and margin are rebuilt from the canonical governing criterion, preventing aggregate drift. |
| Publication chain | One sanitizer correlates current evidence through calculation record, project save/load and loaded provenance, download, autosave and report. UI, overview and report use mm for width and MPa for decompression. | Missing/malformed criterion source or applicability, stale value/status/governing element, changed solver evidence or non-finite nested evidence invalidates publication. |

The consolidated audit adds 56 independent nodes beyond the prior 387,
bringing cumulative lean F-043 evidence to 443 checks. Its bounded closure gate
contains 227 core SLS/source-policy nodes and ten direct calculation-record,
project, download/autosave, UI, report and overview nodes. Exact-head external
gates remain mandatory; this matrix does not self-certify PR closure.

- Codex Review of
  `fe5cf369127bd1f2ebdaa1b8da320f6e67d4fe88` found that a criterion with a
  valid status but scalar or mapping `matched_responses` could reach aggregate
  rebuilding and raise before the later publication evidence checks. One typed
  matched-response normalizer now rejects non-list containers, non-text labels
  and duplicates before aggregation; the defensive aggregate and top-level
  acceptance paths share it. Boolean, text and mapping controls plus project
  save/load and report publication regressions fail closed. The five new
  independent nodes bring cumulative unique affected evidence to 443 checks.

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
  finding invalidated that closure gate. Review of the first F-043 head
  `2a095acc932b242c2465fac0c1b0d1ddfc59c102` then found the cross-case
  duplicate-mapping P1 described above. Review of
  `65d730011691a6a05f99df91090746f469224be8` found the interrupted-repair and
  pre-solver Boolean P1s described above. Review of
  `02120ed094dfe22509dafa336d6416e065faaa82` found the iterable-container P2
  described above. Independent QA of
  `2f32782b3d69262742d59dfaac9a38d49ef18bf6` found the calculated-width P1 and
  mapping/non-Iterator P2 described above. Review of
  `bc6ce9e9020fa33d8c8e9c02edbc94b313328668` found the informational-response
  validation P1 described above. Review of
  `ac195dead08a4cb807267ca8f3f23092afd09fec` found the decompression-order P2.
  Review of `ef6896a389498ad61b8813a0335577a70ec54633` found the corresponding
  calculation-record P2. Codex Review and CI then accepted
  `ef9045071a49442e2f53fa1f7da81096aa9f3a18`, but independent QA found the
  stale-PASS publication P1 described above. Review of
  `0729cb8a641b860e0dec16de01ada39f60ff193a` then found the governing-evidence
  correlation P1 and report `NOT APPLICABLE` P2 described above. Review of
  `855caff3c0355ba30c6b114ae909d53578087d0a` then found the all-matched-width
  P1 and full-decompression-correlation P2 described above. Review of
  `5b9a8bc528af9b34818b6b06e5dd1d1bf22bda59` then found the missing-required-
  combination and all-matched-decompression P1s described above. Review of
  `add0713c468d77ddfe38f6a022d2825ee3545d6d` then found the raw
  all-matched-decompression and report coarse-role issues described above.
  Review of `c76677d0b5f18cf0baa99877cba91056ec41bfe4` then found the
  incomplete decompression evidence and known-failure precedence issues
  described above. Review of
  `2352d3bfc3316f10cce07e6850b91df1d7d65501` then found the
  non-finite audit-evidence issue described above. All are locally remediated.
  New exact-head Codex Review, GitHub CI, original independent QA closure and
  merge remain pending; this implementation log does not self-certify closure.
