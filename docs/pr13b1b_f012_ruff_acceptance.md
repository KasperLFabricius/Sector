# PR-13B1B / F-012 Ruff acceptance boundary

## Exact base and fresh slice

- Exact base: `main@c67ea2b3640580786f4b12e2c316c5f142d11e93`.
- Application version: `0.91`.
- Rejected PRs #347 and #348 are negative evidence only. Their heads are not reused, patched, reopened, cherry-picked or merged.
- This slice owns Ruff only. Coverage is already accepted; mypy and dependency security remain independent later F-012 slices.

## Frozen contract

1. `app`, `sector`, `tools` and `tests` are checked for Ruff runtime-error selectors `E9`, `F63`, `F7` and `F82`.
2. The accepted capacity boundary (`sector/capacity.py` and `tests/test_capacity.py`) is checked with `E4`, `E7`, `E9`, `F` and `I` and has no ignored rule.
3. `tests/test_project_io.py` receives the same selected rules. Its retained repository-root bootstrap owns the sole `E402` waiver, including a named owner, reason and exit condition.
4. Every later candidate compares scope IDs, paths, selectors and ignored rules with the contract in its exact accepted Git base. Scopes, paths and selectors cannot shrink; ignored rules cannot expand.
5. Every ignored rule maps one-to-one to an owned waiver. Removing a satisfied waiver remains possible, while adding an ignored rule fails the accepted-base ratchet.
6. Pull-request, every-main-push and manual triggers remain unfiltered. The test job, validator step and runner step cannot be skipped or made non-propagating.
7. The Ruff runner is one Python command that executes each frozen scope in isolated mode and stops with failure on the first non-zero Ruff result. Repository Ruff configuration cannot add hidden ignores, and a later passing scope cannot conceal an earlier failure.

## Evidence and exclusions

- Focused tests exercise current checks, a controlled Ruff failure, persistent accepted-base ratchets, waiver lifecycle, Git-object baseline loading and workflow mutations.
- Directly affected workflow, reproducibility, package-contract and legal tests plus cheap ASCII/version/static guards run before publication.
- No whole-tree formatting is performed. No mypy, dependency-security, solver, formula, standard, result, schema, Streamlit, report/manual, package, signing, release, application-version, v0.93 or rejected-head work is included.
