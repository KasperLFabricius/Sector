# PR-14C2R2 acceptance: raw source snapshot and package identity

## Bounded objective

This clean replacement implements F-021 C2 only. It derives package time and
identity from one exact authenticated commit, preserves create-only evidence,
and verifies packaged source against raw Git blob bytes. It does not implement
the two-build comparison (C3), consolidated publication gates (C4), application
behaviour, UI, solver, report, manual, or a version change.

PR #370 and branch
`codex/pr14c2-source-epoch-identity-20260807-122432` are preserved negative
evidence. No code or commit from that closed candidate is in this branch.

## Acceptance matrix

| Boundary | Accepted authority | Fail-closed rejection |
|---|---|---|
| Commit selection | Exact lowercase 40-hex commit read with replacement objects disabled | Ref, abbreviation, uppercase, missing or non-commit object |
| Package time | Canonical nonnegative committer epoch and its exact UTC rendering | Negative/zero-padded/out-of-range epoch, mismatched UTC or `SOURCE_DATE_EPOCH` |
| Source seal | Raw commit/tree, epoch/UTC, file/byte counts and inventory SHA-256 | Missing, noncanonical, extra, ambiguous or coherently resealed evidence |
| Build input | New exact raw commit export and hash-locked isolated environment | Mutable worktree, Git/Python inherited controls, pre-existing run/generated path |
| Manifest | Canonical create-only JSON derived only from the strict environment seal | Git/checkout/wall-clock fallback, unknown/missing/mismatched field, overwrite |
| Package source | In-memory authenticated raw blobs for complete `app`, `sector`, and `assets` inventories | Matching worktree/package mutation, changed/missing/extra source, link/reparse/nonregular entry |
| Publication | Independent verifier in unsigned QA and protected release workflows before upload/signing | Evidence, manifest, raw closure, license, notice, executable or source mismatch |

The crucial replacement invariant is that package comparison never rereads the
mutable exported build source. The expected bytes remain the raw authenticated
blob payloads captured from Git, so a concurrent writer cannot make a changed
package authoritative by changing the build directory to match it.

## Initial-review correction

The initial exact-head review identified one localized P2: child entries were
checked for Windows reparse points, but the package root and `_internal`
ancestor could themselves be a symlink or junction. The corrected verifier
preserves the lexical package path, non-following-stats every ancestor from the
package root through each source-tree root, and rejects a link, reparse point,
missing ancestor, non-directory ancestor, or boundary escape before traversal.

## Dependency audit repair

The strict Actions audit on the preserved candidate reported 43 advisories.
The replacement retains the narrow fixed lock set only: GitPython 3.1.58,
pypdf 6.15.0, and pytest 9.1.1. Hashes are regenerated; no advisory ignore,
certificate bypass, threshold change, or gate weakening is introduced.

## Recorded local evidence

- red oracle: missing `snapshot_commit` caused the expected collection failure;
- exact exporter/build contracts: 64 passed, 1 inherited symlink skip;
- release policy and packaging contracts: 39 passed before the two additional
  raw-snapshot hostile cases were added;
- final package acceptance, matching-mutation, and coherent-reseal subset after
  the repeated raw-byte authentication pass: 3 passed;
- initial-review ancestor-reparse red oracle: 3 expected failures;
- corrected root/ancestor/raw-snapshot subset: 6 passed;
- corrected release, unsigned-QA, and packaging guard set: 48 passed;
- corrected C2 plus all pypdf-affected publication suites under a fresh exact
  hash-locked environment: 398 passed, 2 inherited skips;
- dependency, coverage, Ruff, mypy, legal, reproducibility, unsigned-QA,
  ASCII, and version guards: 349 passed;
- lock preflight, enforced Ruff policy, and enforced strict mypy policy: clean;
- local advisory retrieval remained fail-closed because the Sweco TLS
  interception chain is not trusted by the isolated Python environment;
  certificate validation was not disabled and GitHub Actions remains the
  authoritative clean-network audit;
- Sector version remains 0.91;
- no unsigned executable was launched;
- QA outputs and prior evidence were not removed or overwritten.
