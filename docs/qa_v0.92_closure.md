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
| F-003 | PR-03 | Closed and merged | The 2023 crack-control core distinguishes mild reinforcement and prestressing steel, derives per-tendon `xi1`, and fails closed on invalid contribution evidence. | `tools/pr03_crack_oracle.py`; frozen `SLS-2023-XI1` and independent scalar direct-tension formulas. | Mixed/prestress-only, bond, diameter, invalid-input, decompression, persistence/publication, report/manual and provenance regressions; consolidated exact-head evidence accepted. | GitHub CI and Codex Review accepted exact head `298117e5583c5f4ff0d881ecdba6df1e9c5fe4ec`; all threads resolved. | `QA CLOSURE ACCEPTED - 298117e5583c5f4ff0d881ecdba6df1e9c5fe4ec` | [PR #206](https://github.com/KasperLFabricius/Sector/pull/206); squash `760db72914f341b9d69a4033ef2676f75bf10ced` | No `xi` or edition applicability is inferred; the selectable 2023 method remains subject to the project design basis. |
| F-004 | PR-02 | Closed and merged | Danish fatigue presets resolve `gamma_s,fat = 1.20 x 1.10 x gamma0 x gamma3` and `gamma_c,fat = 1.45 x 1.10 x gamma0 x gamma3`; preset, approved-final override, and migrated legacy values have distinct persisted states and report derivations. Approved final overrides and their approval are retained outside preset widget state. PR-02 originally blocked unresolved legacy values; the authoritative PR-04 analysis-versus-conformance policy now retains and calculates positive finite values with a qualified conformance state without reopening F-004. | At unity category factors, `gamma_s,fat = 1.32` and `gamma_c,fat = 1.595`; all edition selections, non-unity categories and override persistence remain asserted. PR-04 adds values 0.5 and 2.0 plus missing/contradictory approval and legacy-review controls as cross-cutting F-005/F-010 evidence. | `tests/test_fatigue_inputs.py`; `tests/test_fatigue_analysis.py`; `tests/test_project_io.py`; Streamlit switching/reload and live/durable controls in `tests/test_app_smoke.py`; PDF evidence in `tests/test_report.py`. | Eleven earlier actionable threads plus the later interrupted-project-load finding were resolved; Codex Review accepted PR-02 exact head `c789ad9bfc94921f3383e9bce3c056b8e445cdcd`. | `QA CLOSURE ACCEPTED - c789ad9bfc94921f3383e9bce3c056b8e445cdcd` | [PR #205](https://github.com/KasperLFabricius/Sector/pull/205); squash `91bb63f9bd05050f508334202ca531367420062e` | Under the superseding cross-cutting policy, old saved positive finite factors remain actual calculation inputs. Without a dedicated approved custom basis they yield `REVIEW / NOT FULLY ASSESSED`, not a standard PASS. |
| F-005 | PR-04 | Implemented on branch; exact-head external gates pending | A distinct `DS/EN 1992-2:2005 + AC:2008` method records inherited, overridden, added and not-assessed checks; calculates brittle Method b, separate box-wall torsion, bridge SLS stress/crack routing, separate web/flange minimum reinforcement and bridge concrete fatigue; mandatory unsupported states block overall PASS. One canonical conformance record now separates numerical validity from the selected-standard prescription: positive finite custom `cot(theta)`, `k`, Miner `C` and fatigue material factors are retained and calculated, while deviations produce visible `REVIEW / NOT FULLY ASSESSED` or a qualified `APPROVED CUSTOM` verdict and are never relabelled as a standard PASS. | Controlled local standard matrix plus independent `tools/pr04_bridge_oracle.py` examples for brittle reinforcement, common-angle wall torsion and both angle bounds, corrected concrete Miner life, bridge SLS limits and the web/flange `k` dimension rule. Frozen false-PASS examples `cot(theta)=10`, `k=0.01` and standard Miner `C=100` retain analytical results but cannot emit an unqualified standard PASS. | Canonical conformance, bridge/fatigue core, raw adapter, mutable publication evidence, Streamlit, project/autosave/download state, cache/signature, report and manual regressions; exact-head focused/full counts are recorded after the final implementation SHA. | Pending exact-head Codex Review after commit and CI. | Pending original reviewer. | Pending | Methods a/c, added bridge web/interface interaction, shear/torsion fatigue, deflection and opened segmental-joint checks remain explicit blocking `NOT ASSESSED` when applicable. F-020 remains excluded. |
| F-006 | PR-05 | Planned | Add distinct DS/EN 1992-2 + DK/NA:2015 methodology and Danish bridge choices. | To be established in owning PR for road, footbridge, and railway cases. | Pending | Pending | Pending | Pending | None accepted. |
| F-007 | PR-03 | Closed and merged | EN 1992-1-1:2023 uniform direct tension is calculated only for the validated solid-rectangle/opposed-face domain; unsupported or incomplete states are explicit blocking dispositions. | Standalone rectangular perimeter-area, reinforcement-ratio, strain, spacing and crack-width oracle in `tools/pr03_crack_oracle.py`. | Direct-tension, transition, unsupported-domain, decompression, SLS precedence and app integration regressions accepted on the exact head. | GitHub CI and Codex Review accepted exact head `298117e5583c5f4ff0d881ecdba6df1e9c5fe4ec`. | `QA CLOSURE ACCEPTED - 298117e5583c5f4ff0d881ecdba6df1e9c5fe4ec` | [PR #206](https://github.com/KasperLFabricius/Sector/pull/206); squash `760db72914f341b9d69a4033ef2676f75bf10ced` | 2005 direct tension and non-rectangular/combined all-tension inputs remain explicitly `NOT ASSESSED`; they cannot yield PASS. |
| F-008 | PR-03 | Closed and merged | The engine records dominant direction/scope, while UI, overview, saved limitations, manual and report state that orthogonal or inclined crack systems are not assessed. | Rotation oracle compares an asymmetric section and reinforcement under rigid rotations with transformed loads. | Rotated engine cases plus app summary, report text/raster and manual content gates accepted on the exact head. | GitHub CI and Codex Review accepted exact head `298117e5583c5f4ff0d881ecdba6df1e9c5fe4ec`. | `QA CLOSURE ACCEPTED - 298117e5583c5f4ff0d881ecdba6df1e9c5fe4ec` | [PR #206](https://github.com/KasperLFabricius/Sector/pull/206); squash `760db72914f341b9d69a4033ef2676f75bf10ced` | Directional limitation remains explicit until PR-06 supplies an applicable opt-in multidirectional method. |
| F-009 | PR-06 | Planned | Keep independent `Vx`/`Vy` results but prevent combined PASS without a selected applicable interaction method. | To be established in owning PR for uniaxial limits, balanced biaxial load, axis swap, rotation, and interaction boundary. | Pending | Pending | Pending | Pending | No universal interaction rule will be inferred. |
| F-010 | PR-04 | Implemented on branch; exact-head external gates pending | The corrected DS/EN 1992-2 Expression (6.106) route prescribes `C = 14` under the bridge methodology. Any positive finite coefficient remains an analytical input, but a different value is recorded as a deviation and can never be labelled as the AC:2008 relation or an unqualified standard PASS. A separately named Miner/S-N methodology plus explicit source/approval can emit only a qualified custom verdict. Core, preparation, project/session, UI, bridge publication and report boundaries revalidate the actual coefficient, conformance record, method, applicability and typed whole-calculation methodology binding against the calculation snapshot. | Controlled local DS/EN 1992-2:2005 clause 6.8.7(101) with AC:2008 correction and DS/EN 1992-1-1:2023 E.8 applicability; independent `tools/pr04_bridge_oracle.py` standard `C = 14` life/damage plus standard-labelled and approved-project `C = 100` examples. | Included in the consolidated core/project/publication, report, manual, adjacent-fatigue, rendered, policy and Streamlit slices recorded for PR-04, including the exact `C = 100` false-PASS reproducer, mutable evidence and cache/signature controls. | Pending exact-head Codex Review after commit and CI. | Pending original reviewer. | Pending | Project-basis adoption outside the bridge method remains an explicit engineering-authority decision with a recorded approval source; another S-N relation remains a separately sourced project method and is never relabelled as Expression (6.106) or 2023 E.8. |
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
| F-043 | PR-03 core closed and merged; PR-04 bridge-base inheritance/override implemented; PR-05 Danish bridge override pending | PR-03 canonically separates response duration from SLS combination and binds every accepted criterion to immutable current response evidence across raw, project/session/autosave and report boundaries. PR-04 reuses that mechanism for DS/EN 1992-2 Table 7.101N rather than a generic maximum; missing, ambiguous, malformed or stale routing remains `NOT ASSESSED / REVIEW`. | Frozen ordinary 2004 QP `0.22 mm` versus unrelated `0.31 mm` at `0.30 mm`; 2023 appearance/durability/decompression routes; bridge base Table 7.101N member/prestress routes and missing-combination controls. | PR-03 independent closure included 33 routing/correlation and decompression probes plus 52 canonical-body/schema mutation probes. PR-04 adds bridge routing, alias, malformed-evidence, persistence, UI/report and headless regressions within its bounded 775-pass gate. | GitHub CI and Codex Review accepted PR-03 exact head `298117e5583c5f4ff0d881ecdba6df1e9c5fe4ec`; PR-04 exact-head review is pending. | `QA CLOSURE ACCEPTED - 298117e5583c5f4ff0d881ecdba6df1e9c5fe4ec` for PR-03 core; PR-04/PR-05 inheritance/override closure remains sequential. | [PR #206](https://github.com/KasperLFabricius/Sector/pull/206); squash `760db72914f341b9d69a4033ef2676f75bf10ced` for PR-03 core | PR-05 must add the Danish bridge matrix, especially the DK non-prestressed frequent-column route; required decompression remains `NOT ASSESSED` without complete concrete-stress evidence. |

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

Scope was frozen after the two `c76677d` P1 remediations. The same-family stop
condition then triggered on the independent-QA rejection of `96f60c75`; before
another push, full CI or Codex Review, the raw-assessment and publication paths
were refactored and audited as one state model:

| Invariant family | Accepted state | Blocking state and retained evidence |
| --- | --- | --- |
| Required response count | Exactly one explicit response identity; consistent fine/coarse aliases may share it. | Zero matches, multiple independent identities, duplicated table identities or an empty/malformed table scope give `NOT ASSESSED / REVIEW`. |
| Identity and combination | Current response identity and required combination agree with the table-wide mapping scope. | Missing/stale identity, missing required combination, scope mismatch or a conflicting alias combination blocks routing without inferring from duration. |
| Alias context | All labels sharing an identity agree on combination, duration, mapping provenance and solver provenance. | Any conflicting field blocks the whole routed criterion; no alias is silently demoted to informational. |
| Immutable acceptance binding | Every accepted criterion has one strictly validated, schema-versioned, SHA-256-fingerprinted binding covering criterion metadata/applicability, required combination, matched label/ID aliases, explicit duration/mapping/solver provenance, calculated/governing evidence and a complete non-empty table scope. | Wrong body/container/field shape, missing provenance, empty/truncated scope, duplication, tampering or an independently reconstructed mismatch gives `NOT ASSESSED / REVIEW`; stored contexts are not replaced before this comparison. |
| Decompression evidence | `OK`/`EXCEEDED` carries typed status, finite signed MPa value, governing concrete location and solver provenance consistent with the response context and every alias. A solver-proven `NOT APPLICABLE` may omit value/location. | Missing, Boolean, non-scalar, non-finite, changed or conflicting status/value/location/provenance gives `NOT ASSESSED / REVIEW`; nested `NaN`/`Inf` cannot cross publication. |
| Response role | Every current response mapped to the required combination is a criterion input; explicitly different combinations remain informational. | A required alias marked informational, a hidden/new required response or an unaccounted independent response invalidates stored PASS/FAIL evidence. |
| Aggregate precedence | `INVALID` > `EXCEEDED` > `NOT ASSESSED` > `OK` > `NOT APPLICABLE`; a known exceedance remains FAIL while incomplete criteria remain visible. | Published top-level status, value, limit, utilization and margin are rebuilt from the canonical governing criterion, preventing aggregate drift. |
| Publication chain | The raw and publication boundaries share one canonical body validator, sealer and binding comparator through calculation record, project save/load and loaded provenance, download, autosave and report. UI, overview and report use mm for width and MPa for decompression. | Fingerprint-valid but structurally malformed bodies, text-typed width/limit numerics, missing/malformed criterion source or applicability, stale value/status/governing element, changed identity/duration/mapping/solver evidence or non-finite nested evidence invalidate publication without raising. |

The canonical-binding refactor adds 138 table-driven nodes beyond the prior 443,
bringing cumulative lean F-043 evidence to 581 checks. Its refreshed bounded
closure execution covers 775 nodes across core SLS, routing/source policy,
calculation record/session, project save/load/provenance, download/autosave,
manual/report and rendered-artifact boundaries. Exact-head external gates remain
mandatory; this matrix does not self-certify PR closure.

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
  non-finite audit-evidence issue described above. Independent QA of
  `96f60c75d6e9efbd6b6b94b3f1615c0eded0c96f` then found that stored acceptance
  was not immutably bound to response identity/duration/mapping/solver
  provenance. The first canonical refactor at
  `1446ee35630591803f4c0ce4f0f95abc9ec80df2` was rejected by Codex Review for
  fingerprint-valid malformed body shapes, missing/empty/truncated table scope
  and nullable accepted-response provenance. That same-family P1 triggered the
  user-directed stop condition again: sealing and publication now share the
  strict complete-body validator, the scalar compatibility adapter constructs
  an explicit complete scope, and adversarial raw-to-publication/project/session/
  autosave/report tests fail closed without exceptions. Review of
  `d12796a8bda246f51a228162e67f7feefdbe0c7e` then found that a
  fingerprint-valid text crack width could survive numeric coercion and raise
  during outcome reconstruction. The canonical validator now requires typed
  width and limit numerics, and the same adversarial binding is blocked through
  publication, project round-trip, report, download, session and autosave. All
  are locally remediated.
  Exact head `298117e5583c5f4ff0d881ecdba6df1e9c5fe4ec` then passed GitHub
  CI and Codex Review with all threads resolved. The original reviewer returned
  `QA CLOSURE ACCEPTED - 298117e5583c5f4ff0d881ecdba6df1e9c5fe4ec`
  after 33 routing/correlation and decompression probes, 52 canonical-body/schema
  mutation probes, independent engineering spot checks and the final ledger
  inspection. [PR #206](https://github.com/KasperLFabricius/Sector/pull/206)
  was squash merged as `760db72914f341b9d69a4033ef2676f75bf10ced`.

## PR-04 evidence log

- Scope: F-005, F-010, and the DS/EN 1992-2 bridge-base inheritance/override
  portion of F-043 only.
- Controlled local source: `DS/EN 1992-2:2005 + AC:2008`. The implementation
  records each relationship to DS/EN 1992-1-1:2004 as inherited, overridden,
  added, or not assessed; no normative internet source was used.
- Implemented bridge checks include prestressed brittle-failure Method b per
  tensile region, every box wall at one common strut angle, inherited member
  shear with explicit bridge-interface applicability, inherited reinforcement
  fatigue, the AC-corrected bridge concrete Miner route, characteristic concrete
  stress, structured Table 7.101N crack/decompression routing, and separate web
  and flange minimum reinforcement including the shrinkage floor.
- Methods a/c, added bridge web/interface interaction, shear/torsion fatigue,
  deflection, and opened segmental-joint checks are explicit blocking
  `NOT ASSESSED` dispositions when applicable; unsupported scope cannot yield an
  overall PASS.
- `tools/pr04_bridge_oracle.py` is independent of Sector calculation code and
  covers brittle minimum reinforcement, box-wall torsion, concrete fatigue,
  bridge SLS stress/crack routing, and web/flange minimum reinforcement.
- One canonical bridge record and evidence fingerprint now crosses calculation,
  project save/load/provenance, session/autosave/download, UI, report, and manual
  boundaries. Malformed Boolean/non-finite/duplicate/stale evidence fails closed.
  Ordinary EN 1992-1-1 use can be qualified as an approved project adoption only
  with an explicit source; without it, the positive finite analytical result is
  retained as `REVIEW / NOT FULLY ASSESSED`.
- Bounded local evidence is green: 387 bridge/SLS/fatigue core checks; 214
  project/presentation/manual checks with one skip; 142 report checks; 3
  rendered-artifact checks; 19 version/package/executable-free provenance
  controls; and 10 focused Streamlit calculation/session/download/autosave
  checks. These are 775 passing nodes and one intentional skip.
- Fresh manual, ordinary-fatigue report, and representative bridge report
  artifacts passed structural/raster preflight and visual inspection. The source
  Streamlit server returned a healthy HTTP 200 response; the in-app browser
  webview itself did not attach after two bounded attempts, so interaction
  evidence remains the focused Streamlit AppTests rather than a claimed live
  browser walkthrough.
- Version remains exactly `0.91`. F-020, ignored `dist`, quarantine,
  unrelated test-temp directories, and unsigned executables remain untouched.
- External exact-head GitHub CI, Codex Review, and original independent QA
  closure remain mandatory after the PR-04 commit; this implementation log does
  not self-certify closure.
- Codex Review of `72e0c25f677c88d8d8bcf2735213a9bb9aaaa264`
  found five fail-open integration paths: inherited member shear was coupled to
  added bridge detailing, hollow geometry could omit its wall matrix, the bridge
  crack adapter trusted unbound or duplicated acceptance records, and selecting
  the bridge fatigue edition could imply bridge authority outside the active
  whole-calculation methodology. The remediation gives inherited shear its own
  required check, makes hollow-section wall coverage physically mandatory,
  shares the canonical immutable SLS binding validator between raw bridge
  adaptation and publication, requires exactly one independently matched bridge
  criterion, and invalidates bridge-owned Miner applicability when the whole
  bridge method is inactive or exited.
- Post-review evidence is green: 23 focused review-facing SLS/bridge/fatigue
  cases; 395 affected core checks; 214 project/presentation/manual checks with
  one intentional skip; 142 report checks; five focused Streamlit interactions
  covering the changed Inputs-to-Analysis-to-Inputs route and adjacent fatigue
  state; 3 rendered-artifact checks with the 32 known Kaleido warnings; 19
  version/package/build controls; the independent bridge oracle; compilation;
  and whitespace validation. The next commit is a new exact head, so CI, Codex
  Review, and original independent QA must all be repeated before merge.
- Exact-head CI run `30327436712` on
  `ad7d191910e2b4ed9128eb6018a47cc53c370543` passed 1,926 tests with one skip
  but exposed two stale UI-contract assertions: the workflow-order fixture
  omitted the new bridge-methodology expander, and the legacy scalar adapter
  still expected no inactive bridge publication record. Both expectations now
  assert the intentional UI and `NOT APPLICABLE` publication contract. The two
  exact regressions plus adjacent bridge UI and autosave/download publication
  controls pass (4 checks); all exact-head external gates restart after this
  test-only correction.
- Exact head `7018dffb6702703595a76c59aa6f3a52377fe671` then passed CI run
  `30328492185` and exact-head Codex Review, but original independent QA rejected
  it on three bounded normative-parameter P1 findings. The bridge concrete Miner
  route allowed arbitrary `C`, box walls allowed `cot(theta)` outside the inherited
  6.2.3(2) domain, and bridge Expression (7.1) allowed `k` outside the image of
  the 7.3.2(102) dimension rule.
- The authoritative product requirement supersedes that overly strict
  remediation. Sector is an analysis/design tool: a positive finite value can be
  mathematically usable while deviating from the selected standard. The canonical
  parameter-conformance record therefore carries the actual value, selected
  standard, prescribed value/range, standard methodology/source, parameter basis,
  custom methodology, approval/source, applicability and conformance state.
  Boolean, non-finite, zero/non-positive divisors and malformed structures remain
  hard errors; a standards deviation is never clamped or silently replaced.
- The three independent examples are now closed without either false PASS or
  prohibited analysis. `cot(theta)=10`, minimum-reinforcement `k=0.01`, and a
  standard-labelled Miner `C=100` retain their analytical result and exact input,
  but the selected-standard verdict is `REVIEW / NOT FULLY ASSESSED`. A complete
  explicit custom methodology plus approval/source can produce a qualified
  `APPROVED CUSTOM PASS/FAIL`; it is never labelled as the DS/EN 1992-2 check.
  Standard `C=14`, in-range common-angle walls and dimension-derived `k` retain
  ordinary standard PASS/FAIL behavior.
- Stored evidence is independently recomputed at publication. Mutated values,
  reordered/missing conformance records, contradictory basis/approval metadata,
  changed methodology and stale aggregate verdicts invalidate UI/project/report
  publication even if a bridge fingerprint was recomputed. Inputs and conformance
  evidence participate in calculation signatures and are retained through live
  state, durable mirror, project/autosave/download, solver evidence and report.
  Exact-head focused/full counts, rendered artifacts, package-content verification,
  CI and review evidence remain pending until the final implementation SHA.
- Fresh Codex Review of exact head
  `50d811c9d99a47b890f5a6172469cfcafdfc2d1a` identified two publication-boundary
  defects before closure: a top-level method relabel could bypass the Miner
  parameter check, and a malformed `errors` container could crash or discard
  invalid evidence. The obsolete CI run was cancelled when those findings became
  actionable.
- The shared fatigue publication validator now binds
  `concrete_parameters.method` to every enabled concrete method before
  method-specific dispatch, and requires the error container to be a list or
  tuple of non-blank typed messages. A mismatch or malformed container forces
  `valid = converged = passed = False` before the Streamlit or PDF boundary.
  Thirteen direct reproductions and boundary checks pass, followed by all 283
  affected fatigue/report checks and two focused Streamlit controls. Exact-head
  CI, Codex Review and original independent closure remain pending after commit.
- Fresh Codex Review of exact head
  `76b4cf65a6d7c9e392aaac988145b48b75994876` then found that bridge applicability
  was still derived from the claimed Miner-basis label. Relabelling only a
  component-method project adoption as the bridge-standard basis could therefore
  suppress the project-source requirement at publication. The obsolete CI run
  was cancelled immediately.
- The correlation model now carries the typed whole-calculation design
  methodology from validated preparation into the analysis signature and result
  payload. One shared publication boundary compares that immutable result binding
  with the calculation input snapshot before the overview, result view, bridge
  methodology or report may use the verdict. Missing, changed or conflicting
  methodology/basis evidence is invalid; the bridge basis is no longer trusted to
  establish its own applicability. The method/basis/methodology matrix, headless
  validation, bridge adapter, project, UI and report checks pass within a
  385-check affected core/project/report slice, three focused Streamlit checks
  and 149 manual/ASCII controls. Exact-head CI, Codex Review and original
  independent closure remain pending after commit.
- Codex Review of exact head
  `918f3a00698010af2566abb764fe080dc0202ee0` found two remaining P1 correlation
  gaps. The Streamlit split-cache key omitted design methodology, so switching
  from component methods to the bridge method could reuse the old fatigue payload
  and remain INVALID instead of recalculating. The PDF boundary also replaced a
  missing methodology in a legacy/direct input snapshot with component methods,
  allowing a component-method result to remain publishable without its current
  correlation evidence. The obsolete CI run was cancelled immediately.

| Methodology-correlation boundary | Required invariant | Missing or changed evidence |
|---|---|---|
| Validated preparation and solver signature | One typed methodology is carried into the prepared calculation, solver-facing signature and result payload. | Invalid input produces an explicit invalid fatigue result; it cannot acquire bridge authority from a Miner-basis label. |
| Streamlit split-result reuse | The fatigue reuse key includes the same methodology in addition to every fatigue numerical/provenance input. | A methodology change makes the key unequal and forces a new fatigue calculation before the result snapshot is replaced. |
| Calculation input snapshot, session and autosave | The result payload and the exact input snapshot retain the methodology that produced the calculation. | Legacy results without a matching snapshot remain hidden or publication-invalid rather than being correlated against live inputs. |
| Overview, result view and bridge adapter | Each boundary passes the raw snapshot methodology to the shared publication validator. | Missing, malformed or conflicting methodology forces `valid = converged = passed = False`. |
| PDF report | The report passes the raw calculation-input methodology without a default. | A missing direct/legacy report snapshot is explicit unavailable evidence and publishes `INVALID - fatigue not assessed`. |
| Stored Miner basis and method | Method, basis, coefficient/source and whole-calculation methodology are jointly validated. | Relabelling any one field cannot establish its own standard applicability or preserve PASS. |

- Exact reproductions now recalculate the fatigue payload and snapshot after a
  component-to-bridge methodology switch, and fail closed when report input
  omits methodology. The consolidated source audit found one fatigue reuse key
  and four publication callers; all now use the same typed methodology binding
  without a publication fallback. Six direct/adjacent reproductions, all 386
  affected fatigue/bridge-adapter/project/report checks, five focused Streamlit
  controls and 149 manual/ASCII checks are green. Compilation, whitespace,
  version `0.91` and changed-file controls are green; no executable was touched
  or launched. The new exact head must restart CI and Codex Review.
- Codex Review of exact head
  `53ff19ce6ac7bf3b6a99311538ad1e472cef17fb` found one further same-family P1:
  the bridge record validated its stored methodology and fingerprint but did not
  accept the current calculation-input methodology, so a bridge PASS could be
  published or saved beside component-method inputs. The review also found a P2
  governing-row defect: a supported positive-infinite fatigue failure was reduced
  to a null utilisation before ordering and could yield its source/result position
  to a finite passing row. The obsolete CI run was cancelled.

| Bridge publication invariant | Canonical behavior |
|---|---|
| Immutable solver body | Check bodies, configuration errors and the evidence fingerprint are validated without importing mutable current-input context into that fingerprint. |
| Current input correlation | Every bridge publication call must supply the raw whole-calculation methodology. Missing, malformed or non-bridge context emits a separate typed `REJECTED` publication-validation block and forces `INVALID`. |
| Project hash meaning | A bridge snapshot with rejected methodology correlation cannot set `matches_saved_inputs = true`, even if its stored SHA-256 equals the current canonical input hash. |
| Boundary consistency | Calculation record, overview, bridge view, project dump/load provenance, download, session/autosave and PDF use the same required-context validator; none may invent a default methodology. |
| Unbounded fatigue evidence | Positive-infinite FAIL is represented by a finite-JSON-safe `unbounded_utilisation` marker, explicitly governs finite rows, and retains its result/source through the bridge check and report. |

- The required-context signature makes an omitted bridge-publication argument a
  programming error. Correlation errors are reconstructed for each boundary and
  remain separate from the immutable solver fingerprint, so changing only the
  current context cannot contaminate or permanently rewrite the stored evidence.
  Direct, overview, report, project, calculation-record, download/session and
  autosave controls cover accepted, component-method, missing, Boolean and unknown
  contexts; an independent mixed infinite/finite fatigue pair covers governing
  result/source preservation. Twenty direct cross-boundary cases, all 501 affected
  bridge/fatigue/project/presentation/report checks, seven focused Streamlit
  controls and 149 manual/ASCII checks are green. Compilation, whitespace,
  version `0.91` and changed-file controls are green; no executable was touched
  or launched. The next exact head must restart all external gates.
- The final implementation audit found one remaining durability gap:
  standalone fatigue conformance was present in live solver/report evidence but
  was not retained in the input-hash-bound calculation record. The canonical
  `sector.fatigue-conformance-evidence/v1` snapshot now carries the actual
  material factors and Miner coefficient, selected standard and whole-calculation
  methodology, standard/custom method, source/approval, parameter and aggregate
  conformance, analytical verdict, qualified verdict and selected-standard
  verdict. Its SHA-256 seal covers the exact JSON body; every project, load,
  download and autosave boundary also reconstructs the parameter records and
  aggregate verdict before retaining it.
- Valid approved custom factors `0.5` and `2.0` plus project Miner `C=100`
  round-trip through project provenance and are shown with their methodology and
  sources in the loaded Save / Load audit summary. Value mutation, a recomputed
  top-level verdict relabel, changed methodology, malformed validity/convergence
  flags and stale aggregate evidence are rejected. A rejected record is removed
  from durable/download/autosave output and cannot preserve an input-match claim.
- The issued-report render fixture now states its component-method calculation
  context explicitly. This preserves the fail-closed rule for missing methodology
  while restoring the intended 23-figure report contract; report and manual
  raster gates pass with all four grouped-fatigue figures present. Final
  exact-head full-suite, artifact, package, CI and review evidence is recorded
  only after the implementation commit.
