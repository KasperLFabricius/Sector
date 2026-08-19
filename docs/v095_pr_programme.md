# Sector v0.95 pull-request programme

## 1. Programme outcome

Sector 0.95 is a maintenance, engineering-correctness and bounded-usability
release. It closes the numerical, fail-closed, persistence,
publication-lifecycle, browser-safety and qualification weaknesses found by
the adversarial review of Sector 0.94, together with bounded additions that the
owner has authorized for this release. It adds no selectable design basis,
geometry family, global compliance claim, certification claim or engineering-
approval claim.

The historical immutable owner choices are recorded in the
[v0.95 decision register](v095_decision_register.md). The reviewed
`owner_sequence_graph` in `tests/fixtures/v095_review_cases.json` is the
machine-readable authority for PR identities and dependencies. PR-A00a2 makes
that graph visible in this narrative and the lifecycle policy. PR-A00b freezes
the authorized outcomes and their acceptance owners, while each named
implementation PR still owns its exact matrix. Each implementation slice must
start from the accepted code and the structured adversarial cases in
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

The controlled lifecycle is `Planned` -> `In progress` -> `Merged`. The
dependency graph, rather than table order, controls when a slice may start.
PR-01 through PR-14, PR-A00a1, PR-A00a2, PR-A00b and PR-A01 through PR-A10
retain product version 0.94. Gate G1 starts only after every one of those
development PRs has merged. It is the sole complete pre-bump qualification.
Only PR-15 may change governed version surfaces; gate G2 qualifies that bumped
head for release.

| Order | Slice | Depends on | Initial status |
|---|---|---|---|
| 1 | PR-01 - Programme, decisions and adversarial fixture freeze | released v0.94 baseline | In progress |
| 2 | PR-02 - Plastic M-M envelope origin containment | PR-01 | Planned |
| 3 | PR-03 - Prestress-only cracking classification | PR-01 | Planned |
| 4 | PR-04 - Hollow torsion real-wall cap | PR-01 | Planned |
| 5 | PR-05 - Combined M-V-T prerequisite closure | PR-02, PR-03, PR-04, PR-A03 | Planned |
| 6 | PR-06 - Material constructor domain invariants | PR-05 | Planned |
| 7 | PR-07 - Section and elastic finite-result invariants | PR-06 | Planned |
| 8 | PR-08 - Plastic sweep range and endpoint contract | PR-02, PR-07 | Planned |
| 9 | PR-09 - Killable and recoverable publication exporter | PR-03, PR-07 | Planned |
| 10 | PR-10 - Decoded-content upload identity | PR-06, PR-07 | Planned |
| 11 | PR-11 - Locked atomic autosave and visible retry | PR-07 | Planned |
| 12 | PR-12 - Point-grid DOM text safety | PR-01 | Planned |
| 13 | PR-13 - Mandatory manual PDF QA guard | PR-09 | Planned |
| 14 | PR-14 - Portable-build subprocess and manifest containment | PR-09, PR-13 | Planned |
| 15 | PR-15 - Governed Sector 0.95 version bump | G1 | Planned |

### 2.1 Owner-addition sequence and release gates

The sequence amendment starts from the first main head after the reviewed
torsion subdivision partition-authority slice merged:

- amendment base: `main@ed3a94098eed7e76521e5e9a3e27e86c66226f60`
- amendment base tree: `790083ac2694bc2bfa7578dd8062a047be66c0b5`
- reviewed graph merge: `main@9282a7ff56512b123fbb53a55ebf32565c093fe5`
- reviewed graph tree: `7e6980bb3d107f19336efbb0c2c4ef40f1b6cde1`
- product version: Sector 0.94
- project schema at the amendment base: 25

Historical PR-01 through PR-15 identities are not renumbered. The additions use
PR-A00a1, PR-A00a2, PR-A00b and PR-A01 through PR-A10:

| Order | Slice | Depends on | Initial status |
|---|---|---|---|
| A00a1 | PR-A00a1 - Machine-resolvable owner sequence graph | exact amendment base | Merged |
| A00a2 | PR-A00a2 - Programme narrative and lifecycle integration | PR-A00a1 | Merged |
| A00b | PR-A00b - Owner-addition scope and acceptance ownership | PR-A00a2 | In progress |
| A01 | PR-A01 - Standard-report curvature equation compaction | PR-A00b | Planned |
| A02 | PR-A02 - Closed-stirrup torsion resistance authority | PR-A00b | Planned |
| A03 | PR-A03 - Torsion-link input and publication semantics | PR-A02 | Planned |
| A04 | PR-A04 - Dual user-owned crack-width criteria and schema migration | PR-A00b | Planned |
| A05 | PR-A05 - Simplified reinforcement-fatigue screen | PR-A00b | Planned |
| A06 | PR-A06 - Governing Results Overview | PR-05, PR-A04, PR-A05 | Planned |
| A07 | PR-A07 - Analysis-result hover semantics | PR-A00b | Planned |
| A08 | PR-A08 - Input Eurocode reference provenance | PR-A00b | Planned |
| A09 | PR-A09 - Plastic compression-zone depth summary | PR-A00b | Planned |
| A10 | PR-A10 - End-user manual reference cleanup | PR-A00b | Planned |

The table is a readable projection of `owner_sequence_graph.dependencies`; the
fixture remains authoritative. In particular, PR-A02 and PR-A03 precede PR-05,
and PR-A06 follows PR-05, PR-A04 and PR-A05. No PR-A01 through PR-A10 code may
start before PR-A00b freezes the corresponding outcome and acceptance owner.

`owner_sequence_graph.dependencies.G1` is exactly this complete list, with no
implicit or omitted prerequisite: PR-01, PR-02, PR-03, PR-04, PR-05, PR-06,
PR-07, PR-08, PR-09, PR-10, PR-11, PR-12, PR-13, PR-14, PR-A00a1, PR-A00a2,
PR-A00b, PR-A01, PR-A02, PR-A03, PR-A04, PR-A05, PR-A06, PR-A07, PR-A08,
PR-A09 and PR-A10. PR-15 depends only on G1, and G2 depends only on PR-15.

PR-A00a1 and PR-A00a2 do not freeze an implementation equation, schema key,
threshold, status precedence, tie-break or publication behavior. PR-A00b now
freezes the bounded outcomes and their acceptance owners; the detailed
implementation matrices remain with the named implementation PRs.

### 2.2 Scope outcomes and acceptance ownership

PR-A00b freezes the owner-authorized outcomes and their PR ownership; it does
not substitute a broad umbrella fixture for each implementation contract. Each
PR-A01 through PR-A10 must first freeze its own exact acceptance matrix,
including applicability, authoritative inputs, retained evidence, equations,
units, statuses, ordering, provenance, ties, malformed states, migration,
publication surfaces and exclusions relevant to that slice. Code starts only
after that matrix is reviewable in the same bounded PR.

The authorized outcomes are limited to:

- compact the unbreakable Standard-report ultimate-curvature substitution
  while retaining the complete candidate evidence;
- prevent full torsion resistance from being assessed without current closed
  torsion links, then make shear-link and torsion-link semantics explicit in
  input, results and publication;
- replace the single ordinary crack criterion with independent long-term and
  short-term user criteria, with the exact persistence, migration and Formula
  7.100 isolation contract frozen in PR-A04 before code;
- add a supported simplified reinforcement-fatigue screen before detailed
  reinforcement fatigue assessment;
- replace the scrolling multi-case Results Overview with one always-visible
  governing row per stable check family, without a global project verdict;
- make analysis plot hovers publish retained capacity, material, stress and
  strain evidence while coordinates remain in section input and preview plots;
- add selected-edition Eurocode provenance to creep and detailing inputs;
- publish retained plastic compression-zone depth `c` in the summary without
  relabelling it as generic effective reinforcement depth `d`; and
- remove the complete reproducible reference from the end-user manual while
  retaining its generator, independent oracle, fixture and tests as QA assets.

The detailed contracts intentionally remain with their owning bounded PRs:

- PR-A04 must freeze the two ordinary crack-limit persistence keys and
  duration-matched comparison rules, exact zero/no-comparison behavior, the
  schema-25 ordinary positive/blank migration, and preservation of an enabled
  schema-25 Formula 7.100 operand in a separate schema-26 field. It must also
  freeze malformed-input, disabled-heightened and backward-save behavior before
  implementation; ordinary zero must never become the heightened operand.
- PR-A05 must freeze the exact eligible fatigue detail-class-to-threshold map,
  below/equal/above outcomes, unsupported-detail fallback and preservation of
  independent fatigue checks before implementation.
- PR-A06 must freeze the complete emitted Results Overview status vocabulary
  and precedence, numeric and status tie-breaking, and selected case/direction
  provenance before implementation.

PR-A00b intentionally owns none of those implementation matrices and cannot be
used as implementation evidence for PR-A04, PR-A05 or PR-A06.

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
  that proof they remain unchanged; no unapproved feature enters through the
  v0.95 programme.

## 6. Development test and CI policy

PR-01 through PR-14, PR-A00a1, PR-A00a2, PR-A00b and PR-A01 through PR-A10 run
only:

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

After every development PR in `owner_sequence_graph.dependencies.G1` merges,
the release sequence is:

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
- PR-A00a1, PR-A00a2, PR-A00b and PR-A01 through PR-A10 are merged as accepted
  bounded slices with version 0.94;
- every confirmed P1/P2 adversarial case has objective fail-closed closure;
- every final development head has both required exact-head review receipts and
  zero unresolved threads;
- successful G1 is bound to the final 0.94 main head before PR-15 opens;
- PR-15 raises the version once and G2 passes on the exact merged 0.95 head;
- the tag, release target, main head and qualified source revision are identical;
- the released portable ZIP and checksum match the qualified package hashes;
- reports and the manual pass semantic, structural-PDF and raster review; and
- no global compliance, certification or engineering-approval claim is added.
