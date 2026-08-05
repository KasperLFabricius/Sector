# PR-13B / F-012 quality-gate acceptance boundary

## Exact base and objective

- Exact base: `main@65452fc9013150ff7cff3507debae7bb34ed3d1c`.
- Application version: `0.91` throughout this unpublished slice.
- Objective: make coverage, selected Ruff, strict typing and dependency security
  blocking CI gates without pretending the retained tree is already debt-free.

## Frozen gates

1. The complete test job measures `app` and `sector` coverage and fails below
   50 whole percent. PR-14 owns the exact-head full-suite measurement and must
   raise this floor to the stable whole-percent result if that result exceeds
   50 percent.
2. Ruff fatal/syntax rules `E9,F63,F7,F82` cover `app`, `sector`, `tools` and
   `tests`. The clean capacity boundary additionally owns `E4,E7,E9,F,I` with
   the documented `test_project_io.py` path-bootstrap `E402` exception.
3. Strict mypy covers the already-clean bridge adapter/kernel and manual
   equation contract/publication boundaries. Listed files may not regress;
   expansion is incremental and requires no suppression inside the listed set.
4. `pip-audit` examines the complete hash-locked development environment with
   strict collection, hash enforcement and pip resolution disabled. No
   vulnerability ID is ignored by this slice.
5. The tracked TOML policy is validated before all gates. Every temporary scope
   waiver names its owner, reason and objective exit condition; tests prove
   missing ownership, missing exit, threshold rollback, path drift, duplicate
   identity, disabled security safeguards and workflow drift fail closed.

## Evidence order

- Focused policy and controlled-failure tests.
- Selected Ruff and strict-mypy commands on their exact frozen scopes.
- Directly affected reproducibility, packaging, ASCII and version guards.
- Dependency command syntax and locked-environment installation verification.
  A real online vulnerability query is expected on the GitHub-hosted runner;
  the local Sweco TLS interception is infrastructure evidence, not a package
  waiver or a successful audit.
- The consolidated full coverage/report/manual/package workflow remains PR-14
  work and is not run for this unpublished slice.

## Explicit exclusions

- No solver, formula, standards, result, verdict, schema, persistence, UI,
  report/manual content, package contents or application-version change.
- No whole-tree formatting, generic static-debt cleanup, invented type stubs,
  vulnerability ignore, unsigned executable launch, signing or release.
- No v0.93 roadmap implementation and no rejected-head content.
