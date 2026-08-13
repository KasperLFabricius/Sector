# Sector v0.94 pull-request programme

## 1. Programme outcome

Sector 0.94 will correct the bounded numerical, input, navigation,
visualisation and publication issues found during the owner's review of Sector
0.93. It will add the approved Quick Section geometries and improve the Danish
heightened crack-control workflow without presenting Sector as a complete
Eurocode, National Annex, bridge-owner, certification or sign-off system.

The immutable owner choices are recorded in the
[v0.94 decision register](v094_decision_register.md). Product implementation
must not start from this narrative alone: every slice has a separate acceptance
matrix derived from the accepted code, retained fixtures and applicable source
material.

Exact starting point:

- Git revision: `c1086a2cb8b20a8339ae72bf30218b0b8c6c4dfe`
- Git tree: `1ac7905eb5e6fd48cce50def16f769a7e8458be0`
- product version: Sector 0.93
- current project schema: 24
- tracked programme worktree and index: clean at programme start
- report reproduction revision: `95eadcd19e313a581aefb507bc69bdc3f8b793e2`

The starting revision already contains PR #399's square-root and C4-1
equation-rendering correction. Sector 0.94 preserves that correction and adds
visual regression coverage; it does not duplicate the fix.

## 2. Pull-request sequence

The controlled lifecycle is `Planned` -> `In progress` -> `Merged`. Completed
slices form one contiguous prefix, at most one following slice is in progress,
and the public version remains 0.93 until PR-14 passes the complete gate.

| Order | Slice | Depends on | Initial status |
|---|---|---|---|
| 1 | PR-01 - Programme, decisions and fixture freeze | v0.93 baseline | In progress |
| 2 | PR-02 - Prestressed N-M endpoint convergence | PR-01 | Planned |
| 3 | PR-03 - Exact-zero fatigue range and result clarity | PR-02 | Planned |
| 4 | PR-04 - Eurocode source registry and tooltip coverage | PR-01 | Planned |
| 5 | PR-05 - Schema 25 and global crack-width criterion | PR-04 | Planned |
| 6 | PR-06 - Dual DK NA heightened crack control | PR-05 | Planned |
| 7 | PR-07 - Structured validation and input navigation | PR-05 | Planned |
| 8 | PR-08 - Stateful material-family tabs | PR-07 | Planned |
| 9 | PR-09 - Dedicated Report workspace and durable profile recovery | PR-07 | Planned |
| 10 | PR-10 - Useful Brief report | PR-09 | Planned |
| 11 | PR-11 - Report table typography and visual regression | PR-10 | Planned |
| 12 | PR-12 - Responsive shear-plot annotations | PR-07 | Planned |
| 13 | PR-13 - Expanded Quick Sections | PR-08 | Planned |
| 14 | PR-14 - Full qualification and Sector 0.94 release | PR-01 through PR-13 | Planned |

## 3. Frozen acceptance boundaries

### Numerical corrections

- The N-M solver must use the exact tensile and compression endpoints for the
  first and last samples. Interior interpolation, reachability rules and solver
  tolerances are unchanged.
- An exactly zero fatigue action increment must reuse the long-term endpoint,
  producing exactly zero stress range, infinite life and zero Miner damage.
  Small but non-zero increments must not be erased.
- Fatigue result surfaces must distinguish Miner damage from prestressing-steel
  proof/yield stress utilisation.

### Crack-control data contract

- Project schema 25 owns one optional analysis-level permitted crack width used
  by ordinary and heightened crack control.
- Schema 24 migrates identical or blank per-case values directly. If populated
  criteria conflict, schema 25 adopts the conservative minimum and presents a
  visible migration warning; the source file is never modified in place.
- The Danish heightened calculation evaluates fine and coarse systems together.
  Each system has its own effective tension area. Diameter, reinforcement
  modulus and provided reinforcement area are derived from retained ordinary
  crack-control evidence, with element/material provenance.
- The sole crack-enabled case is the heightened reference automatically;
  otherwise the user selects it explicitly. Diameter uses the ordinary override
  or largest contributing mild bar, reinforcement modulus uses the conservative
  minimum for contributing mild materials, and provided area is their retained
  sum. Missing or indeterminate evidence fails closed.

### User interface and reports

- Blocking validation is represented as typed, individually rendered issues.
  Navigation opens the owning workspace and input stage; exact browser-cell
  focus is not promised where native Streamlit does not expose it.
- Material families are stateful peer tabs. Expensive hidden content is gated.
- Report is a peer workspace to the right of Analysis. It owns every
  report-specific metadata field and option as well as generation and download;
  Inputs keeps only project-file operations and non-report application
  information. Generation records the frozen input hash and whether results
  were reused or recalculated.
- Report-profile state is normalised before its keyed control mounts. Recognised
  legacy labels migrate; an unknown `rep_report_content` value is removed from
  live, durable and pending state, resets safely to Standard with a visible
  notice, invalidates any old report artifact and never aborts app execution.
- Brief includes the relevant geometry, reinforcement, materials, actions,
  analysis settings, criteria, warnings and governing results. Four pages is a
  typical target; complex multi-case projects may use approximately four to six
  pages when required for readable evidence.
- Report typography acceptance is visual. Table subscripts, radicals,
  fractions, headers, footers and page transitions must be checked on rendered
  pages.

### Quick Sections

The approved additions are trapezoid, L-section, I-section, U-section and
circular hollow/annulus. Inverted T is an orientation of the existing T-section.
Each generator must prove area, centroid, ring/void topology, valid dimensions,
reinforcement containment, preview and project round-trip.

## 4. Risk-based test policy

Development PRs run only:

1. independent oracle/contract tests for the changed family;
2. directly affected existing tests; and
3. cheap compile/import, version, base and scope guards.

Solver-heavy, publication-wide and packaging-wide suites are not repeated on
unrelated PRs. PR-14 first runs the complete static, numerical, UI,
report/manual and schema regression gate while the product still identifies as
0.93. Only after that passes does PR-14 raise every governed version surface to
0.94 and run the complete exact-head regression, identity, reproducibility,
source-release, portable-startup and packaging gates against the bumped build.

## 5. Review and merge protocol

Every slice starts from the exact accepted `origin/main` head and records its
base, head, scope, exclusions and focused evidence. It publishes one immutable
candidate head for exact-head review. The GitHub Codex Review integration must
review the complete final head. Any finding is corrected and `@codex review` is
retriggered; merge is blocked until that exact head has no open Codex finding.
Local or subagent review is supplementary and cannot substitute for this gate.
One localised correction class is permitted. Independent or repeated
substantive findings cause reslicing rather than scope growth.

After a clean exact-head review, the PR head, formal reviews, comments and
thread-resolution state are inspected once more before merge. Post-merge checks
confirm accepted-tree equality, local/origin alignment, version stability and
preservation of unrelated artifacts.

## 6. Definition of done

Sector 0.94 is complete only when:

- PR-01 through PR-13 are merged as accepted bounded slices;
- every frozen decision and supplied-review issue has objective closure;
- current-schema and approved schema-24 migration paths pass;
- the pre-bump complete regression gate passes at 0.93;
- the version is then raised and the complete exact-head 0.94 qualification and
  portable package gates pass against that bumped head;
- reports and the manual pass semantic, structural-PDF and raster review;
- the product version is raised exactly once in PR-14; and
- no global compliance, certification or engineering-approval claim is added.
