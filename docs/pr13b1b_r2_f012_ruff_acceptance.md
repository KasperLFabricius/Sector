# PR-13B1B-R2 / F-012 Ruff acceptance boundary

## Exact base and fresh lineage

- Exact base: `main@c67ea2b3640580786f4b12e2c316c5f142d11e93`.
- Application version: `0.91`.
- Rejected PRs #347, #348 and #350 are negative evidence only. No rejected head, commit, patch, branch content or review candidate is reused.
- This fresh slice owns Ruff only. Coverage is already accepted; mypy and dependency security remain independent later F-012 slices.

## Frozen policy

1. `app`, `sector`, `tools` and `tests` are checked for runtime-error selectors `E9`, `F63`, `F7` and `F82`.
2. `sector/capacity.py` and `tests/test_capacity.py` are checked with `E4`, `E7`, `E9`, `F` and `I` and no ignored rule.
3. `tests/test_project_io.py` uses the same selectors and owns the only ignored rule, `E402`, with a named owner, reason and exit condition.
4. Each invocation is isolated from repository Ruff configuration, ignores source-level `noqa` suppression and does not respect Git-ignore filtering. The policy file is the only source of ignored rules.
5. Every later candidate compares its ordered scope, path and selector inventory and its ignored rules with the policy stored in the exact accepted Git base. Accepted coverage cannot shrink or reorder, and ignored rules cannot expand.
6. Every ignored rule maps one-to-one to an owned waiver. A satisfied waiver can be removed, but a new ignore cannot bypass the accepted-base ratchet.
7. Pull-request, every-main-push and manual triggers remain unfiltered. Full-history checkout, exact baseline expression, a single-command validator and a single-command executor remain unconditional and failure-propagating.
8. The executor stops at the first non-zero Ruff scope. A later passing scope cannot conceal an earlier failure.

## Evidence and exclusions

- Focused tests run the live policy and independently attempt repository-configuration, line-level `noqa`, file-level `noqa` and Git-ignore bypasses, plus contract, baseline, waiver, order and workflow mutations.
- Directly affected workflow, reproducibility, package-contract and legal tests plus cheap ASCII/version/static guards run before publication.
- No whole-tree formatting, mypy, dependency-security, solver, formula, standard, result, schema, Streamlit, report/manual, package, signing, release, application-version, v0.93 or rejected-head implementation is included.
