# PR-14C4R2 consolidated publication acceptance

## Final bounded objective

This is the designated final full-gate implementation slice. It starts from
accepted C3 main `e4a8f319fe2b8bfc57a711d84be36b56d20b3a6f` and changes only
QA/publication policy, its adversarial tests and this acceptance record. Sector
remains version `0.91`; application, solver, schema, report/manual content,
Streamlit behavior, package content and protected signing mechanics are
unchanged.

## Consolidated fail-closed chain

The ordinary Windows QA workflow is one exact ordered chain:

1. full-history source checkout and pinned Python;
2. preflight plus hash-locked QA installation;
3. create the retained QA-evidence root;
4. validate the complete consolidated workflow contract;
5. validate and execute the locked online dependency audit;
6. validate the non-shrinking coverage, Ruff and strict-mypy ratchets and run
   their executable policies;
7. run the complete test suite with coverage;
8. render the real-figure report and manual fixtures even when an earlier test
   fails, then retain their diagnostic evidence;
9. upload the complete QA evidence; and
10. only after the full test job succeeds, build two distinct exact-source
    unsigned Windows packages, authenticate both, compare every package byte
    twice and retain both witnesses plus canonical comparison evidence.

The workflow has exactly these two jobs. Required steps cannot disappear,
duplicate, reorder, skip, continue after failure or change working directory.
The workflow root is also exact: its name, triggers, permissions, concurrency
policy and job inventory are frozen, and no inherited `env`, `defaults` or
other top-level execution setting may alter either job outside their canonical
digests.
Every external action retains its exact approved repository, full commit and
inputs. Canonical digests freeze both complete parsed job mappings, including
every command, environment mapping and shell. Secret-context detection is
independent of expression whitespace, access syntax and quoted closing braces.
QA evidence retention is 14 days and dual-build evidence retention is 7 days.
The ordinary QA workflow contains no secret or signing authority and never
launches an unsigned package. The manual protected-release workflow and its
sole secret-bearing signing step remain independently guarded by the accepted
PR-14A/C policies.

## Reslice boundary

Rejected PR #375 and its branch remain preserved at head
`e0a3d1b60b8ae43d8c6ff74805acc3484129535f` as negative evidence. Its
corrected-head review exposed a quoted-brace secret-context bypass, substitution
of a different full-SHA action and mutable package command mappings. This R2
slice starts fresh from accepted C3 main and closes those three defect classes
with red-first adversarial contracts; it does not inherit rejected ancestry.

PR #376's initial exact-head review then identified one bounded defect: a
workflow-level `env` or `defaults` mapping could alter both jobs without
changing either canonical job digest. Red-first adversarial cases now require
the complete top-level contract as well as both exact job contracts. This is
the sole review correction permitted on the R2 slice.

## Final coverage calibration

The temporary `coverage-pr14-calibration` waiver has satisfied its exit
condition and is removed. The accepted floor rises irreversibly from 50% to 90%
for `app` plus `sector`. The immediately preceding immutable C3 exact-head run
measured 90.95% across 16,811 statements, providing a small honest execution
margin while preventing material regression. Later accepted candidates cannot
lower this floor, remove a target or silently reintroduce a waiver.

## Required final evidence

- adversarial consolidated-workflow and coverage-policy contracts;
- retained dependency, coverage, Ruff, mypy, unsigned-package, reproducibility
  and protected-release policy tests;
- enforced Ruff, strict mypy, pyflakes and py_compile checks;
- one immutable exact-head GitHub workflow with the live dependency audit,
  complete regression at the 90% floor, real-figure report/manual renders, two
  exact-source Windows builds, both identity checks and byte comparator green;
- affected desktop and 390/768/1280/1920-pixel Streamlit viewport inspection;
- structural and raster inspection of the exact generated report/manual PDFs;
- exact review, squash-tree, parent, version, workbook, evidence and rejected-
  ancestry verification.

## Explicit exclusions and residual release boundary

No dependency is upgraded without a live audit finding. No signing secret,
certificate, publisher identity, approval or reputation result is fabricated.
The protected workflow may be dispatched only with genuine external signing
authority; its absence remains an external release limitation, not a bypass or
test failure. No v0.93 roadmap behavior or version change is included.
