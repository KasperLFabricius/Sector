# Sector v0.92 QA closure ledger

This ledger is the implementation-side index for the sequential v0.92 closure
program. "Implemented" does not mean independently closed. A row becomes closed
only after GitHub CI, current-head Codex Review, and the original independent QA
reviewer all accept the same full commit SHA and that exact head is merged.

The ledger is updated in every owning PR. Pending rows deliberately do not claim
an oracle, regression, reviewed SHA, or closure that has not yet been produced.

| Finding | Owning PR | Implementation status | Calculation or presentation behavior | Independent oracle or benchmark | Regression tests and generated artifact evidence | Codex Review iterations / reviewed head | Independent adversarial closure SHA | Merged PR | Accepted residual limitation |
|---|---|---|---|---|---|---|---|---|---|
| F-001 | PR-01 | Implemented on branch; review and closure pending | One winding-independent, scale-aware topology gate now blocks malformed, non-finite, degenerate, repeated, backtracking, self-contacting/crossing, outside/touching/crossing-hole, overlapping, and nested-hole geometry in UI, project I/O, API, raw helpers, and solver entries. | Frozen `G-VALID-CONCAVE`, `G-INVALID-BOWTIE`, `G-INVALID-COLLINEAR`, `G-INVALID-HOLE-OUTSIDE`, and `G-INVALID-HOLE-OVERLAP` cases; test-only exact-rational segment/containment oracle. | `tests/test_geometry_topology.py`; `tests/fixtures/geometry_topology_f001.json`; focused Streamlit pre-solver smoke test; project v14 mixed-winding round trip; existing geometry, solver, shear, torsion, fatigue, capacity, and hand-calculation regressions. | Pending | Pending | Pending | Exact terminal closure markers and forward intermediate collinear vertices remain valid; raw winding/order is preserved and analysis copies are oriented canonically. |
| F-002 | PR-02 | Planned | Separate Danish concrete compression and tension material-factor routing for torsional concrete resistance. | To be established in owning PR from separate base EN and DK/NA hand calculations. | Pending | Pending | Pending | Pending | None accepted. |
| F-003 | PR-03 | Planned | Apply reinforcement type/bond and `xi1`-weighted prestress contribution to 2023 effective reinforcement ratio. | To be established in owning PR for mixed reinforcement and limiting `xi1` cases. | Pending | Pending | Pending | Pending | None accepted. |
| F-004 | PR-02 | Planned | Edition-aligned Danish fatigue defaults with derived provenance and persistent explicit overrides. | To be established in owning PR from Danish fatigue provisions. | Pending | Pending | Pending | Pending | None accepted. |
| F-005 | PR-04 | Planned | Add distinct DS/EN 1992-2:2005 + AC:2008 methodology with explicit inheritance, bridge overrides, applicability, and non-pass unsupported states. | To be established in owning PR from the four-layer standards comparison and independent bridge examples. | Pending | Pending | Pending | Pending | None accepted. |
| F-006 | PR-05 | Planned | Add distinct DS/EN 1992-2 + DK/NA:2015 methodology and Danish bridge choices. | To be established in owning PR for road, footbridge, and railway cases. | Pending | Pending | Pending | Pending | None accepted. |
| F-007 | PR-03 | Planned | Add standard-supported uniform/direct-tension crack-width path and blocking unsupported-scope state. | To be established in owning PR for pure tension, near-zero curvature, and decompression. | Pending | Pending | Pending | Pending | None accepted. |
| F-008 | PR-03 | Planned | Expose the current one-directional crack-control limitation in results and conclusions until an applicable opt-in method is selected. | To be established in owning PR with rotated asymmetric cases. | Pending | Pending | Pending | Pending | Directional limitation remains explicit until PR-06. |
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

## PR-01 evidence log

- Scope: F-001 only.
- Standards routing: not applicable; this PR validates computational geometry
  before any standards method is selected.
- Tolerance and compatibility policy: `docs/geometry_topology.md`.
- Frozen evidence: `tests/fixtures/geometry_topology_f001.json`.
- Independent oracle: exact rational area, segment-intersection, and containment
  predicates implemented only in `tests/test_geometry_topology.py`.
- Focused evidence: 48 topology/entry tests; 140 geometry/section/project tests;
  201 complete Streamlit smoke tests; solver-family, hand-calculation, shear,
  torsion, fatigue, version, packaging, and compatibility batches all green.
- Full local suite: 1,396 passed, 1 skipped, 32 rendering warnings; version
  remained exactly `0.91`.
- Reviewed v14 project evidence: the supplied `sector_section.json` loads through
  the canonical gate without migration or point reordering.
- Review, CI, independent closure, and merge fields remain pending until they
  refer to the same immutable full head SHA.
