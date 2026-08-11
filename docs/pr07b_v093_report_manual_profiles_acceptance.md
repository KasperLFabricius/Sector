# PR-07B Sector v0.93 manual/report profiles acceptance

Status: candidate acceptance contract for the PR-07B development branch.
PR-07A is merged. GitHub must record the final PR-07B candidate, accepted tree,
checks and squash identity; this document does not invent the remote real-
figure or package gates that have not yet run.

## Accepted upstream base

- Programme branch: `codex/pr07b-v093-report-manual-profiles`
- Upstream PR-07A squash revision: `0b2ec0735a5f65b3889f2b5ec906f30399ccec11`
- Accepted upstream tree: `934a288ed67d6f2d6c43b6f201f5e012eef054d1`
- Governing identity: [Sector product identity](product_identity.md)
- Living programme: [Sector v0.93 PR programme](v093_pr_programme.md)
- Decision register: [Sector v0.93 decision register](v093_decision_register.md)
- Upstream acceptance: [PR-07A equation-renderer acceptance](pr07a_v093_equation_renderer_acceptance.md)

PR-07A passed its exact-head complete test, real report/manual render and
two-build unsigned-package workflows before squash merge. PR-07B starts from
that accepted squash without altering solver or project-schema identity.

## Owner-confirmed objective

PR-07B makes the existing calculations easier to find, review and issue. It
adds immutable Brief, Standard and Audit presentation profiles; reorganises the
manual around task, input and method reading paths; and improves report review
density without recalculating, suppressing or changing an engineering result.

Every requested calculation remains in every profile's compact results
overview. Complete textbook substitutions remain limited to the globally
governing or extremal example selected by the completed calculation payload.
Five Elastic cases therefore do not create five worked crack calculations. The
first-generation Danish fine/coarse crack branches remain the deliberate
separate-example exception when both are part of the selected method.

## Immutable report profiles

`app.report_profiles` is a standard-library-only registry of frozen, slotted
and hashable policies. The exact profiles are:

| Profile | Purpose | Depth contract |
| --- | --- | --- |
| Brief | Rapid review | Every requested result/status plus the retained globally critical calculation register; no broad derivation or audit inventory; hard three-page frozen-fixture limit. |
| Standard | Ordinary design review and product default | Used inputs, complete result tables, live used methods, material calculation steps and key provenance. Internal `EQ-*` keys and exhaustive branch evidence are hidden. |
| Audit | Expanded retained evidence | Canonical inputs, every retained live step/branch, full provenance, hashes and theory context. It explicitly does not mean approved, compliant or certified. |

The legacy `qa_appendix=False/True` boundary maps exactly to Standard/Audit.
The exact earlier schema-24 labels `Default report` and `Default report + QA
appendix` migrate to Standard and Audit respectively. Conflicting, unknown or
incorrectly typed selections fail closed and clear any previously generated
report instead of silently selecting a shallower profile. Figures remain a
separate option. Profile selection participates in persistence/autosave and
report freshness, but not the calculation-input digest.

For one immutable completed result payload, profiles retain identical values,
display rounding, statuses, warnings, units and sources. Profile code does not
call a solver, material law, result selector or governing-rank function.

## Report information architecture and density

Every profile begins with document control, project/source identity, profile
scope and the complete requested-results overview. The overview is one stable
publication table grouped in this order:

1. acceptance checks, with failures, invalid results, review items and
   not-assessed states before ordinary successful rows;
2. calculated output-only quantities; and
3. scope and not-run states.

The table retains every original row, value, criterion, status and governing
flag. It may use one semantic continuation page, with its caption/header
repeated, while its lead-in stays on the first page and governing-marker note
stays on the last. Standard overview text is at least 8.5 pt. Brief uses a
deliberately compact 7.2 pt overview with reduced cell padding to meet its hard
three-page limit without dropping a row.

The frozen browser-free reference fixture currently produces 3 Brief pages,
46 Standard pages and 57 Audit pages. Standard exceeds its 30-page target
because the representative fixture intentionally enables every calculation
family and retains the complete used-input/result tables plus one globally
critical derivation per implemented method. Shrinking below the accepted type
floor or removing a requested result would be worse than the excess. Final
browser-free review inspected all 46 pages in colour and grayscale and approved
the exception: content is unclipped and legible, headings remain with their
first substantive row, and reducing to 30 pages would require a result/detail
omission or a type-size breach. The final real-figure CI artifact remains a
separate exact-head gate.

## Manual information architecture

The PDF and self-contained HTML manual share one standard-library-only
destination registry. It defines the exact five input stages, nine result
views, implemented-method destinations, three reading paths, required task
workflows and indexed troubleshooting categories. The Streamlit application
derives its visible stage and result-view labels from the same registry.

The front matter offers direct Start-here routes for quick calculation, input
reference and method reference. Task workflows cover section creation,
materials/reinforcement, actions, Elastic/crack, plastic/capacity, fatigue,
detailing, result review, save/load, report-profile selection and the portable
application. Input-reference tables reuse the seven canonical editable-table
registries and publish label, notation, unit, definition, sign, blank/default
behaviour, validation and method dependency. A dedicated N-M Interaction result
destination closes the previous navigation gap.

Limitations and troubleshooting are indexed by symptom, cause and correction,
including malformed geometry, crack not requested, intentionally blank ordinary
criterion, stale results, project-version rejection, publication failure and
portable-build prerequisites. Stable PDF/HTML anchors connect workflows, input
stages, result views and methods.

## Accessible companion and document control

The current ReportLab PDF is not described as tagged or accessible. The same
release therefore provides an equivalent, semantic, self-contained HTML manual
with `lang=en`, no script or external resource, valid heading hierarchy,
resolving internal links, scoped table headers, selectable equation
alternatives and figure text alternatives/captions.

The PDF carries title, non-anonymous author, subject, keywords, language,
visible exact version/source revision, detailed outline destinations, chapter
headers and version/revision/page footers. Manual body, table, caption,
reference and equation roles are at least 9.5 pt with leading of at least 1.25
times the type size. Muted text is darkened from `#808080` to `#5A5A5A`.
The repeated document-control furniture is the reviewed exception: running
headers are 7.5 pt and footers are 8 pt. They are not body, table, caption,
reference or equation content, and every colour/grayscale page was checked for
legibility.

## Affected-surface matrix

| Surface | PR-07B change | Frozen boundary |
| --- | --- | --- |
| Report policy | Add immutable Brief/Standard/Audit policies and exact legacy mapping. | Presentation only; no solver, result schema, schema-version change or calculation digest. Schema-24 projects migrate the two exact earlier labels into the existing presentation mapping. |
| Report PDF | Group overview rows, apply profile-owned chapter/table depth and add profile scope. | Every requested result/status remains; worked selection is consumed from retained identities only. |
| Streamlit report controls | Replace binary QA choice with required Brief/Standard/Audit selection and help. | Standard default; figures independent; profile changes report freshness only. |
| Manual structure | Add reading paths, workflows, input/method/result destinations, troubleshooting and generated profile matrix. | Existing governed equation/publication object spines remain authoritative. |
| Manual PDF | Add detailed navigation, revision furniture, metadata and accepted typography. | ReportLab renderer remains; no claim that the PDF is tagged. |
| Manual HTML | Add semantic self-contained companion download. | No JavaScript, external resources, solver access or app-state dependency. |
| Editable table metadata | Add generated validation and method-dependency text. | Existing table keys, fields, parsing and calculation behaviour are unchanged. |
| Tests/publication fixture | Add cross-profile, IA, HTML, PDF metadata, pagination and density gates. | Local gates remain browser-free; real figures and every-page visual review remain release evidence. |

## Engineering and programme exclusions

PR-07B changes no engineering formula, input value, material law, solver,
interim/final result, status definition, governing selector or result schema.
Runtime/publication version remains 0.92 and project schema remains 24; PR-09
owns the final 0.93 identity transition. Within schema 24, the report profile
moves from calculation-owned scalars to the existing presentation mapping so
it cannot change `input_sha256`. Project save/load and autosave retain it, the
two exact earlier labels migrate in place, and every other unknown value fails
closed.

It adds no generic calculation trace/evidence payload, recorder, DAG, parallel
evaluator, raw iteration history, persisted result history or replacement for
the deliberately reverted previous-programme PR-08 machinery. It also does not
implement the current programme's PR-08 portable packaging scope.

## Current browser-free evidence and visual receipt

Current overlapping local receipts, which must not be summed, include:

- 31 immutable report-profile policy tests passed;
- the final post-CI corrective browser-free report/manual/profile/persistence
  matrix passed 538 nodes,
  with only the two deliberate real-figure artifact nodes deselected;
- the focused final pagination matrix passed 31 nodes and the final manual
  split/navigation slice passed 14 nodes, both overlapping the consolidated
  matrix;
- the final focused profile migration, persistence, autosave and report-
  freshness matrix passed 15 parametrized cases, including browser-free
  Streamlit AppTests;
- the programme, retired-trace, lazy-startup, ASCII and policy-test matrix
  passed 377 nodes;
- Ruff policy, strict mypy policy, the consolidated publication gate, locked
  dependency audit with verified TLS, compilation and diff checks passed; and
- the final independent post-fix Codex review returned CLEAN with no P0-P2
  findings across profile persistence, migration, provenance, comment escaping,
  adoption warnings, legacy API compatibility and acceptance wording; and
- the frozen no-figure artifacts contain exactly 3 Brief, 46 Standard, 57 Audit
  and 58 manual pages.

The recorded browser-free visual receipt is:

| Artifact | Colour pages | Grayscale pages | Review decision |
| --- | ---: | ---: | --- |
| Brief report | 3 | 3 | Clean; hard three-page limit met without dropping a requested row. |
| Standard report | 46 | 46 | Clean; 30-page target exception approved for the all-families QA fixture. |
| Audit report | 57 | 57 | Clean; reviewed sparse non-openers on pages 3 and 17 are semantically justified. |
| User manual | 58 | 58 | Clean; Part transitions, continued tables, typography and furniture are legible. |

The final exact candidate must still pass GitHub's complete test, real
report/manual and two-build unsigned-package workflows on the same exact head.
The real-figure artifacts must receive their final visual/crop approval. GitHub
and the merge record, not this candidate document, record the final head/tree,
evidence artifacts, squash identity and tree parity.
