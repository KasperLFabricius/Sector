# Sector v0.95 pull-request programme

## 1. Programme outcome

Sector 0.95 is a maintenance and engineering-correctness release. It closes
the bounded numerical, fail-closed, persistence, publication-lifecycle,
browser-safety and qualification weaknesses found by the adversarial review of
Sector 0.94. It does not add a new design method, standard, geometry family or
global compliance claim.

The immutable owner choices are recorded in the
[v0.95 decision register](v095_decision_register.md). Each implementation slice
must start from the accepted code and the structured adversarial cases in
`tests/fixtures/v095_review_cases.json`; this narrative is not a substitute for
an independent acceptance matrix.

Exact starting point:

- Git revision: `9abd4c89f71d1379e32085ecc6773e14de882e33`
- Git tree: `f5e98754f0f970749919e354957bfa34dd4eb7fe`
- product version: Sector 0.94
- current project schema: 25
- released tag: `v0.94` at the same exact revision
- final v0.94 QA run: `31769606607`, attempt 1, successful
- tracked programme worktree and index: clean at programme start

## 2. Pull-request sequence

The controlled lifecycle is `Planned` -> `In progress` -> `Merged`. Completed
slices form one contiguous prefix and at most one following slice is in
progress. PR-01 through PR-14 retain product version 0.94. After those slices,
gate G1 is the sole complete pre-bump qualification. Only PR-15 may change
governed version surfaces; gate G2 qualifies that bumped head for release.

| Order | Slice | Depends on | Initial status |
|---|---|---|---|
| 1 | PR-01 - Programme, decisions and adversarial fixture freeze | released v0.94 baseline | In progress |
| 2 | PR-02 - Plastic M-M envelope origin containment | PR-01 | Planned |
| 3 | PR-03 - Prestress-only cracking classification | PR-01 | Planned |
| 4 | PR-04 - Hollow torsion real-wall cap | PR-01 | Planned |
| 5 | PR-05 - Combined M-V-T prerequisite closure | PR-02 through PR-04 | Planned |
| 6 | PR-06 - Material constructor domain invariants | PR-05 | Planned |
| 7 | PR-07 - Section and elastic finite-result invariants | PR-06 | Planned |
| 8 | PR-08 - Plastic sweep range and endpoint contract | PR-02, PR-07 | Planned |
| 9 | PR-09 - Killable and recoverable publication exporter | PR-01 | Planned |
| 10 | PR-10 - Decoded-content upload identity | PR-07 | Planned |
| 11 | PR-11 - Locked atomic autosave and visible retry | PR-07 | Planned |
| 12 | PR-12 - Point-grid DOM text safety | PR-01 | Planned |
| 13 | PR-13 - Mandatory manual PDF QA guard | PR-09 | Planned |
| 14 | PR-14 - Portable-build subprocess and manifest containment | PR-09, PR-13 | Planned |
| 15 | PR-15 - Governed Sector 0.95 version bump | G1 after PR-01 through PR-14 | Planned |

## 3. Frozen engineering boundaries

### Plastic envelope and combined checks

- Radial M-M utilisation is defined only when the accepted, closed plastic
  polygon contains the global moment origin. Zero or small demand must not
  receive a finite PASS when the origin is outside the admissible polygon.
- A combined M-V-T check may consume the plastic result only when the plastic
  envelope is converged, closed and owns a checked utilisation. Active shear,
  link and torsion prerequisites must likewise be valid. Missing, capacity-only,
  open or non-converged component results make the combined result explicitly
  invalid; no presentation or report layer may reconstruct a PASS.

### Cracking and torsion

- Prestress is a permanent action, but prestress alone placing concrete above
  `fctm` means the section is already cracked. This state has cracking factor
  zero; absence of an externally tensile fibre must not produce positive
  infinity and `cracked=False`.
- A hollow-section effective-wall override must not exceed the nearest measured
  real wall. Values below or equal to that wall retain their explicit meaning;
  values above it are rejected before resistance is evaluated. The report must
  disclose the selected or capped basis without silently increasing capacity.

### Core input and sweep contracts

- Essential material strengths, moduli, factors and strains must be finite and
  satisfy their documented sign and relationship constraints at constructor
  time. Section coordinates, reinforcement data and actions must separately be
  finite before solver execution. Invalid input must never return
  `converged=True`, a finite resistance or a PASS.
- Plastic sweep bounds and increment must be finite, the increment must be
  positive and the upper bound must not precede the lower bound. The lower and
  upper endpoints are each evaluated exactly once. A non-divisible interval is
  uniformly resampled with a step no larger than requested, ends with the exact
  upper endpoint and never overshoots it.

## 4. Frozen lifecycle, persistence and browser boundaries

- Publication image work runs behind a killable child-process boundary. Startup
  has a real readiness handshake; startup and render deadlines are bounded;
  timeout terminates the owned process tree; a later clean attempt can recover.
  Concurrent callers never exchange image bytes. A figures-enabled manual or
  report fails closed before publishing partial bytes, while figures-disabled
  paths do not start the exporter.
- An uploaded project is identified by a digest of the bytes that decoded and
  parsed successfully. Filename is retained as provenance but is not a content
  identity. A failed decode cannot advance the accepted identity, and a changed
  same-name/same-size file must be processed on the next rerun.
- Autosave uses a cross-session lock, a unique same-directory temporary file
  and atomic replacement. The saved-state hash advances only after successful
  atomic replacement. Lock, write or replace failure is visible, remains due
  and is retried with a bounded backoff; it is never reported as saved.
- Point-grid values originating from paste, project data or a selector are
  rendered as text. Unknown text never enters `innerHTML`; option markup remains
  an allowlisted application constant. Hostile values survive as literal text
  without script, event-handler or HTML execution across component reruns.

## 5. QA, package and deferred-maintenance boundaries

- The manual stray-dollar PDF guard is mandatory in the locked QA environment;
  it cannot silently skip because an undeclared optional parser is absent.
- Portable build subprocesses have named phase deadlines, terminate their owned
  Windows process trees on timeout and retain phase-specific diagnostics.
  Required metadata-copy failures also fail the package rather than disappear.
- Dependency declarations match the APIs and direct imports actually used by
  product, tools and tests. In particular, the supported Kaleido lower bound
  in PR-09 must provide the exporter API Sector invokes.
- Cache narrowing, collapsed-work optimisation and dead-code deletion are not
  mandatory v0.95 slices. They require a separately approved bounded PR with
  static and dynamic reachability evidence plus a retained measurement. Absent
  that proof they remain unchanged; no new product feature enters through
  maintenance work.

## 6. Development test and CI policy

PR-01 through PR-14 run only:

1. independent oracle, contract or adversarial tests for the changed family;
2. directly affected existing tests; and
3. cheap compile/import, Ruff, ASCII, version, base and scope guards.

They do not run the complete repository, publication or packaging gates. Each
development PR is one bounded `[skip ci]` commit, and its squash-merge subject
also retains `[skip ci]`, so the main-push workflow is not accidentally used as
an early full qualification. No manual workflow rerun substitutes for this
rule.

Any G1 repair PR uses the same candidate and squash-merge `[skip ci]` rule.
PR-15's candidate commit also contains `[skip ci]`, preventing a pull-request
full run on the bumped branch. Before squash merge, its complete reviewed merge
commit message - subject, body and trailers - is set explicitly and checked
case-insensitively to contain none of `[skip ci]`, `[ci skip]`, `[no ci]`,
`[skip actions]`, `[actions skip]` or a `skip-checks: true` trailer. The clean
`Release Sector 0.95` main push is the G2 trigger, and its exact-SHA Actions run
receipt is required before qualification evidence can be accepted.

After PR-14 merges, the release sequence is:

1. G1 runs the complete static, numerical, UI, schema, report, manual, real-image,
   portable-build and packaged-startup gate while the product is still 0.94;
2. correct any failure in a separate bounded PR that follows the same focused
   evidence and exact-head review protocol, then repeat G1 on the new exact
   0.94 main head;
3. only after a successful exact 0.94 receipt, PR-15 raises every governed
   version surface to 0.95 in one version-only change; and
4. after PR-15 merges, G2 runs the complete exact-head 0.95 qualification and
   package gate before tag and release publication.

The post-bump run is release qualification, not an early development run.

## 7. Adversarial review and merge protocol

Every slice starts from the exact accepted `origin/main` head and records base,
head, tree, scope, exclusions, focused evidence and version. The implementing
agent publishes one immutable candidate head. Before merge, both of these must
review the identical complete final SHA:

1. a fresh independent adversarial reviewer that did not implement the slice;
2. the official GitHub Codex Review integration, triggered explicitly with
   `@codex review` after the candidate is final.

Any push invalidates both receipts. A finding is corrected, focused evidence is
rerun, and both reviews are repeated on the new exact head. Merge is blocked
until both reviews are clean, every review thread is resolved, and one terminal
head/review/comment/thread inspection confirms no late finding or head change.
This requirement includes every G1 repair PR and the version-only PR-15.
Flat comment counts are not sufficient evidence. A second substantive
correction class, repeated P1/P2 findings or scope broadening causes reslicing
rather than an expanding PR.

## 8. Definition of done

Sector 0.95 is complete only when:

- PR-01 through PR-14 are merged as accepted bounded slices with version 0.94;
- every confirmed P1/P2 adversarial case has objective fail-closed closure;
- every final development head has both required exact-head review receipts and
  zero unresolved threads;
- successful G1 is bound to the final 0.94 main head before PR-15 opens;
- PR-15 raises the version once and G2 passes on the exact merged 0.95 head;
- the tag, release target, main head and qualified source revision are identical;
- the released portable ZIP and checksum match the qualified package hashes;
- reports and the manual pass semantic, structural-PDF and raster review; and
- no global compliance, certification or engineering-approval claim is added.
