# PR-06 Sector v0.93 crack-control acceptance

Status: candidate acceptance contract for the PR-06 development branch.
GitHub records the eventual pull request, exact candidate, tree and squash
identities; this document does not invent evidence that has not been run.

## Accepted upstream base

- Upstream PR-05 squash revision: `e622dd1de7649fe2af974120922bd8ba8aec067a`
- Accepted upstream tree: `bf2c8184d5289d1f1e7a17eb69c0e591aa16403a`
- Programme branch: `codex/pr06-v093-crack-criterion-heightened`
- Governing identity: [Sector product identity](product_identity.md)
- Living programme: [Sector v0.93 PR programme](v093_pr_programme.md)
- Decision register: [Sector v0.93 decision register](v093_decision_register.md)
- Upstream acceptance: [PR-05 navigation and modelled-direction acceptance](pr05_v093_navigation_direction_acceptance.md)

PR-05 exact-head Sector QA and its two-build unsigned-package reproducibility
gate passed before merge. PR-05 was squash-merged, its squash tree was verified
exactly equal to the accepted candidate tree above, and this PR-06 branch was
then transplanted onto that squash revision before publication.

## Owner-confirmed objective

PR-06 adds a nullable, user-specified comparison criterion to each eligible
Elastic crack-width row. Sector continues to calculate and publish crack width
without pretending that a criterion exists. When a positive criterion is
provided, it publishes the retained value, limit and ratio with controlled
comparison wording.

PR-06 also adds the separately selected first-generation Danish heightened
crack-control calculation from Formula 7.100 NA. That calculation is a bounded,
section-level check with direct user inputs. It is not inferred from exposure,
bridge ownership, geometry semantics or another load case.

## Ordinary crack-width comparison

`ordinary_crack_criterion_mm` is nullable on each current-schema Elastic row.
A blank value is intentional and leaves the numerical crack width calculated
but acceptance not assessed. A nonblank value must be a positive finite real
number; zero, negative, Boolean, non-finite and malformed values fail closed
without losing the entered source text.

The controlled states are exactly:

- `NOT REQUESTED` when the row does not request crack width;
- `NOT ASSESSED` when no valid numerical width is available;
- `CALCULATED - ACCEPTANCE NOT ASSESSED` when a width exists without a limit;
- `WITHIN USER-SPECIFIED LIMIT`; and
- `EXCEEDS USER-SPECIFIED LIMIT`.

The last two states retain the exact user limit, the `w_k / w_k,criterion`
ratio and a case-owned input-source label. They do not use demand/resistance
`PASS` or `FAIL`, infer an exposure limit, or assert project compliance.

The publication selector ranks eligible ordinary examples by the physical
calculated crack width, never by the comparison ratio. A smaller width with a
tighter user limit therefore cannot displace the actual global crack-width
extremum.

## Design-basis routing

The existing stable design-basis keys, not display labels, dispatch the
ordinary crack capability. The registered route retains the equation edition,
cover-dependent coefficient policy, member-depth policy and whether fine and
coarse branches are reported. Unknown bases and unbound capability/basis pairs
fail closed.

The heightened capability is bound only to the first-generation Danish basis.
It is separately enabled and requires a positive permitted crack width because
that width is an equation operand. It is unavailable for the published 2023
reference option. Sector does not invent a 2023 Danish Annex, Part 2:2023,
confinement enhancement, component mapping or complete bridge capability.

## Heightened section-level result

The direct heightened inputs retain the selected fine/coarse crack system,
ribbed/smooth reinforcement surface, bar diameter, effective tensile strength,
reinforcement modulus, permitted crack width, effective tension area and
provided reinforcement area. The result retains the base and adjusted
reinforcement ratios, required area, provided-area comparison and exact source
identity.

The calculation is attached once at the top level, never repeated inside every
Elastic case. Results Overview publishes its action set, type and source as
`-`, because it is a section-level calculation rather than an Elastic action
set. Its comparison wording remains
`PROVIDED AREA AT LEAST CALCULATED REQUIREMENT` or
`PROVIDED AREA BELOW CALCULATED REQUIREMENT`; this is a bounded area comparison,
not a global verdict.

## Controlled source and independent benchmark

The licensed-source procedure, pinned file identity, title/footer/metadata
anomaly, two independent pixel readings and benchmark values are recorded in
the [Formula 7.100 NA controlled-source evidence](pr06_formula_7_100_na_source_evidence.md).
OCR was used only to locate the relevant pages and was not an implementation or
transcription authority.

The controlled-source evidence record contains only source metadata, reviewer
method, the private-transcription digest and numerical benchmarks. It does not
redistribute the confidential PDF, screenshots, standard prose or the
reviewers' private pixel transcription. The application necessarily contains
the independently reconciled normalized algebra needed to calculate and
publish the check; that implementation is not a substitute for the licensed
standard. Current publisher listing does not replace project-specific
applicability review.

Independent fine/coarse and ribbed/smooth benchmark rows pin every retained
base ratio, required ratio, required area and comparison value. The benchmark
also locks the fine/coarse and smooth/ribbed `sqrt(2)` relationships, positivity,
finite results and the exact area-tie boundary.

## Persistence, replacement and freshness

Project schema remains 24. Current-schema Elastic tables require the exact
column inventory including the nullable criterion. Both save and load validate
the canonical decimal ledger and active row values, so a coherently rehashed
payload cannot smuggle malformed, Boolean, zero or negative criteria through
the JSON boundary.

Ordinary criteria and heightened configuration participate in calculation
signatures, reuse and report freshness. A valid whole-project replacement first
clears all live and durable heightened keys so omitted optional fields cannot
leak from the previous project; valid dormant operands are then restored from
the loaded project. A persisted enabled heightened configuration on an
unsupported basis is hidden and rejected rather than silently rerouted.

## Publication density and readable worked examples

Every named Elastic case remains available as compact result evidence. Full
textbook substitution is intentionally limited to the globally governing
examples:

- the largest physical ordinary crack width, with the governing fine and
  coarse branches when both are part of the selected route;
- one retained ordinary user-limit comparison for that global width; and
- one singleton heightened section-level calculation when it is enabled.

Five Elastic load cases therefore do not produce five full derivations. A
tighter criterion on a non-governing case also does not create another worked
chapter. The report consumes the completed selection identity and never chooses
a different governing case while publishing.

Missing or partial retained operands make the worked calculation unavailable.
Report worked blocks consume retained case operands, while the manual's static
teaching examples consume their authored benchmark values. Neither publication
surface reruns a solver or reconstructs a missing engineering value.
`NOT REQUESTED`, scope limitations and nonconvergence retain their actual reason
and never become an invented statement that the section is uncracked or has no
reinforcement in tension.

## Identity and scope boundaries

PR-06 keeps runtime/publication version 0.92 and project schema 24. PR-09 owns
the final version transition after the complete programme gate. The immutable
PR-01 workbook remains a planning snapshot; living Markdown status changes do
not mutate or rehash it.

PR-06 does not change ordinary solver equations outside the registered route,
add a global code selector, revive the retired generic trace/evidence/DAG
machinery, persist result history, infer exposure, implement confinement or
component-mapped bridge checks, add packaging, or make compliance/certification
claims.

## Verification evidence

Before the final publication-density correction, the affected-surface gates on
the PR-05-restacked candidate produced:

- 931 passed across project I/O, publication objects, design-basis routing,
  SLS, case/load/table contracts, result presentation, reproducible example and
  report/manual equation inventories;
- 194 passed across the complete browser-free semantic report and manual
  suites;
- 13 passed across the focused ordinary/heightened Streamlit AppTest flows;
- 208 passed across trace-retirement, programme, ASCII and lazy-startup
  boundaries;
- 65 passed across complete result presentation and the visible section-level
  heightened attribution AppTest; and
- Ruff policy, strict owned-mypy policy and `git diff --check` passed.

The final correction then received its own current-candidate evidence:

- 4 focused selector/report regressions passed, including the unassessed global
  width versus smaller assessed-width case;
- 215 passed across the complete result-presentation and browser-free semantic
  report suites;
- 198 passed across the whole-tree ASCII, programme and retired-trace guards;
  and
- focused Ruff runtime checks, the full Ruff policy, the strict mypy policy and
  `git diff --check` passed.

After transplant onto the accepted PR-05 squash, an exact-head browser-free
matrix across all changed core, persistence, design-basis, SLS, manual, report,
equation-inventory, reproducible-example and presentation test files produced
1,120 passed. The programme, ASCII and retired-trace group separately produced
198 passed on that restacked candidate.

The controlled-source review independently confirmed the pinned source
metadata and every numerical benchmark, then returned clean after two bounded
P2 evidence corrections. The full restack review preserved symmetric project
ingress validation and the combined Manual table seal. It found and closed two
integration defects: the initial app no longer loads the heavy SLS module, and
the heightened summary cannot inherit an Elastic action-set identity. Final
bounded re-review found no remaining P0-P2 issue.

All local PDF tests were browser-free. No browser, Chrome, Electron, Kaleido or
JavaScript runtime was launched. GitHub must record the final exact candidate
revision/tree and pass the complete coverage, real report/manual render and
two-build unsigned Windows package workflows on that same head before merge.
