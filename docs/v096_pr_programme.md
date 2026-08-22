# Sector v0.96 pull-request programme

## 1. Programme outcome

Sector 0.96 is a publication-quality, usability and bounded engineering-input
release. It corrects the manual/report findings from the adversarial v0.95
review and adds one user-controlled input already contemplated by the selected
DS/EN 1992-1-1:2023 shear method. It does not add a design basis, a global
compliance verdict, certification, sign-off or engineering approval.

The owner decisions are frozen in the
[v0.96 decision register](v096_decision_register.md). The machine-readable PR
graph and review cases are in `tests/fixtures/v096_review_cases.json`. Each
implementation PR must freeze its exact affected-surface matrix before code;
this programme defines scope and ownership, not implementation evidence.

Exact starting point:

- Git revision: `df397b2372e2e49b7a2165b0573ea0913e8c94dd`
- Git tree: `65eb685d0415cfe7852106838bbf51cc216449ab`
- product version: Sector 0.95
- current project schema: 26
- released tag: `v0.95` at `7ab0062de37e08ebcd42330fcefcf62dd717002c`
- current-main QA run: `32584442230`, successful
- tracked programme worktree and index: clean at programme start

## 2. Pull-request sequence

PR-01 through PR-09 retain product version 0.95. They use focused affected
tests and do not run the complete publication/package qualification. Gate G1
qualifies the final 0.95 development head. Only PR-10 may change governed
version surfaces to 0.96; G2 qualifies the exact bumped main head before the
tag and GitHub release are published.

| Order | Slice | Depends on | Initial status |
|---|---|---|---|
| 1 | PR-01 - Programme, decisions and adversarial fixture freeze | current v0.95 main | In progress |
| 2 | PR-02 - Results Overview semantic and presentation contract | PR-01 | Planned |
| 3 | PR-03 - Brief report philosophy and key-figure curation | PR-02 | Planned |
| 4 | PR-04 - Standard and Audit depth separation | PR-03 | Planned |
| 5 | PR-05 - Manual Section A workflows and end-user scope | PR-04 | Planned |
| 6 | PR-06 - User-controlled DS/EN 1992-1-1:2023 gamma_V | PR-05 | Planned |
| 7 | PR-07 - Terminology, exact references and permille notation | PR-06 | Planned |
| 8 | PR-08 - Publication navigation, pagination and typesetting | PR-07 | Planned |
| 9 | PR-09 - HTML/PDF accessibility and clean text layers | PR-08 | Planned |
| G1 | Complete pre-bump qualification | PR-01 through PR-09 | Planned |
| 10 | PR-10 - Governed Sector 0.96 version bump | G1 | Planned |
| G2 | Exact-head v0.96 qualification, package, tag and release | PR-10 | Planned |

The fixture graph is authoritative. The sequence is deliberately linear so
profile, manual, notation and accessibility work always starts from the
accepted publication contract immediately before it.

## 3. Frozen report philosophy

### Results Overview

- The overview is always fully visible and has no fixed-height vertical scroll.
- It contains one governing row for every stable check family that is relevant
  to the current results, not one conclusion per load case.
- A family summary is derived from the same emitted subchecks and cannot say
  `NOT RUN`, `NOT APPLICABLE` or `PASS` when an applicable child row proves a
  contradictory state.
- Failure and warning counts are visible before the table. Informational,
  not-requested and not-run material is separated from governing rows.
- The overview is not a global project or code-compliance verdict.

### Brief

- Brief is a decision summary: calculation identity, selected basis and the
  complete effective calculation inputs used by every active result it
  reports, governing demand/resistance or criterion values,
  utilisation/status and concise limitations. Inactive and unused inputs may
  be omitted.
- Brief never reproduces substitutions, derivations, candidate searches or a
  worked result chain. Existing wording such as `governing result chain` and
  `selected governing worked examples` is removed or replaced accordingly.
- Figures are exceptional. Only the governing plastic and governing elastic
  result plots are included when those analyses are present and report figures
  are enabled. Geometry previews, secondary plots and decorative figures are
  excluded from Brief.
- Retaining inputs is distinct from reproducing the calculation chain. The
  reader can verify what entered the calculation while Standard and Audit
  provide progressively deeper equation and branch evidence.
- Page count is not an acceptance target; information philosophy and readable
  composition control the profile.

### Standard and Audit

- Standard is the normal calculation report. It contains complete used inputs,
  results and one governing worked calculation per active check family, with
  enough source information to review the implemented method.
- Audit retains complete candidates, branches, substitutions, equation/source
  identifiers and provenance needed for detailed reconstruction.
- Standard must be materially shorter and less repetitive than Audit, but no
  numerical input or governing conclusion may disappear merely to meet a page
  target.

## 4. Frozen manual and language boundaries

- Manual Section A Task workflows are action-oriented and route each common
  task or validation error to the correct application stage. They do not tell
  the user to regenerate a report as a general remedy.
- The end-user manual contains current product operation and interpretation,
  not repository contracts, project-schema numbers, build scripts, release
  history, checksum procedures or visual-approval administration.
- The manual never narrates behaviour of former Sector versions.
- User-facing text uses calculation language. `Acceptance checks`, `accepted
  strain plane/state`, `published evidence`, `shared-link authority` and
  similar approval/authority vocabulary are replaced with precise neutral
  descriptions of the implemented calculation and retained result.
- User-facing manuals and reports use the permille symbol `‰`; source-code
  identifiers such as `strain_permille` remain unchanged.

## 5. Frozen DS/EN 1992-1-1:2023 gamma_V contract

DS/EN 1992-1-1:2023 defines `gamma_V` as the partial factor for shear and
punching resistance without shear reinforcement. Table 4.3 (NDP) gives 1.40
for persistent/transient and fatigue design situations, while 8.2.2 uses the
factor in the no-shear-reinforcement resistance expressions.

- A positive finite user value is the calculation value for the selected 2023
  shear method; 1.40 is the default, not a forced constant.
- Boolean, zero, negative, missing and non-finite values are rejected before a
  resistance or verdict is produced.
- The input is active and visible only for the 2023 shear route. Existing
  first-generation EN/DK-NA shear, torsion and combined routes are unchanged.
- The selected value is persisted, migrated, shown with its exact standard
  reference, used by the solver and reproduced in Standard/Audit reports.
- Any schema change is owned by PR-06. Backward loading supplies the 1.40
  default; future or malformed schemas remain fail-closed.

## 6. Frozen reference and publication-quality contract

- Edition and clause labels are exact and consistent across inputs, manual and
  report. This includes the 2023 material routes, creep coefficient and each
  detailing checkbox.
- A project-defined input is labelled as such; Sector does not infer a source
  clause where none controls the value.
- Reports provide visible contents/navigation appropriate to their depth.
  Headings stay with following content, continuation pages contain meaningful
  content, and redundant `See Table/Figure` or generic evidence boilerplate is
  removed.
- HTML has a skip link, real figure alternatives and accessible rendered math
  rather than raw TeX display strings. PDF metadata declares document language
  and hidden QA/source markers do not pollute copied or extracted user text.
- Accessibility work must not change solver values, applicability, selected
  governing results or report-profile depth.

## 7. Development, review and release policy

Each development PR starts from the exact accepted `origin/main` SHA and owns
one bounded family. It records base/head/tree, changed surfaces, exclusions,
focused tests and product version. Validation order is:

1. independent contract/adversarial cases for the changed family;
2. directly affected existing tests;
3. cheap compile, static, version, schema and scope guards.

Use a unique pytest `--basetemp` and preserve prior QA artifacts. Do not use
`git clean`, broad staging or a destructive reset. A candidate is reviewed at
its exact final head; any push invalidates the receipt. A second unrelated
substantive correction class is resliced instead of broadening the PR.

Development candidate and squash-merge subjects include `[skip ci]`. G1 is the
sole complete pre-bump qualification and covers numerical, UI, manual, all
report profiles, accessibility, real images, package and portable startup.
PR-10 then changes version-governed surfaces only. Its final merge message has
no CI-skip directive, so the main push runs G2. Tag `v0.96`, GitHub release and
release assets are published only when G2 passes on that exact SHA.

## 8. Definition of done

Sector 0.96 is ready only when:

- PR-01 through PR-09 are merged as bounded version-0.95 development slices;
- every frozen result/profile/manual/reference/accessibility case has objective
  affected-test closure;
- G1 passes on the final pre-bump main head;
- PR-10 raises all governed version surfaces once and nothing else;
- G2 passes on the exact 0.96 main head;
- the tag, release target, qualified source SHA and packaged assets agree; and
- the manual and all three report profiles pass semantic, extracted-text and
  visual/raster review without expanding Sector's product identity.
