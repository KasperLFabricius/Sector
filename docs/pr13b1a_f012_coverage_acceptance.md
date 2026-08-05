# PR-13B1A / F-012 coverage acceptance boundary

## Exact base and fresh reslice

- Exact base: `main@65452fc9013150ff7cff3507debae7bb34ed3d1c`.
- Application version: `0.91`.
- Rejected PRs #347 and #348, including heads `9f289e708207a4419d94f6ae2c7b8daa558497e1`, `02b09ba5800ccbed438a975b934e5e5cf4ef3f52` and `a1fadb8739e2fe6fd7a4d1db4a302e5cd364b688`, are negative evidence only. None is reused, patched, reopened, cherry-picked or merged.
- This fresh slice owns coverage only. Ruff, mypy and dependency security are independent later F-012 slices.

## Frozen contract

1. The complete QA workflow measures `app` and `sector` and fails below 50 whole percent.
2. Every later candidate compares its coverage target inventory and minimum against the contract stored in its exact accepted base commit. Neither may shrink; raising the floor therefore establishes the next persistent baseline.
3. The test checkout fetches full history so the exact PR base, prior main push or workflow-dispatch parent can be inspected rather than inferred from candidate state.
4. Pull-request, every-main-push and manual triggers remain unfiltered. The `test` job, coverage validator and coverage test step have no skip condition, continue-on-error behavior, dependency gate, job environment or alternate working directory.
5. The contract records the temporary PR-14C calibration owner, reason and exit condition. PR-14C raises the floor when its exact-head consolidated full-suite result permits it.
6. Missing, duplicate, escaping or removed targets; invalid floors; incomplete waivers; inaccessible baseline commits; trigger drift; shallow checkout; baseline-identity drift; command drift; and non-propagating execution contexts fail closed.

## Evidence and exclusions

- Focused tests exercise current alignment, persistent raised floors/targets, self-contained path escape, Git-object baseline loading, workflow structure and controlled failure mutations.
- Directly affected workflow, reproducibility, package-contract and legal tests plus cheap ASCII/version/static guards run before publication.
- The consolidated full suite and final coverage calibration remain PR-14C work.
- No Ruff, mypy, dependency-security, solver, formula, standard, result, schema, Streamlit, report/manual content, package, signing, release, application-version, v0.93 or rejected-head implementation is included.
