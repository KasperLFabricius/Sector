# PR-13B3-R2 / F-012 dependency-security acceptance boundary

## Exact base and rejected negative evidence

- Exact base: `main@1f47b8747be54b48bab6205eef111f8869e4984e`; application version `0.91`.
- Rejected PR #353 heads `17a4bd48f41a113125f11c61778600c737a42187` and `d752887749bb1224e4073711129a554ae8fd9433` are negative evidence only. No rejected head, patch, branch content or review candidate is reused.
- R2 owns the final F-012 dependency vulnerability gate. Coverage, Ruff and strict mypy are accepted.

## Frozen boundary

1. A standard-library-only preflight parses the policy and both flattened locks before the workflow executes any `pip install`. PyYAML is loaded lazily only for the later full workflow validator.
2. The lock parser classifies each nonblank line after trimming whitespace. Only comments, exact pinned requirement declarations and valid SHA-256 hash continuations are accepted. Indented or flush-left index, trust, include, constraint and other control lines fail before installation; orphan/malformed hashes, unexpected indented content, duplicate pins, empty locks and conflicting cross-lock versions also fail.
3. One isolated `pip-audit` process scans `requirements-dev.txt` then `requirements-build.txt`. PyPI service, strict mode, required hashes, pip-disabled collection, JSON output, aliases, compact descriptions, timeout, cache and report path are exact. No fix, dry-run, no-deps, alternate index, ignored vulnerability or waiver path exists.
4. A successful process exit is insufficient. The report must reproduce the independently parsed canonical name/version union exactly once, with no missing, extra, changed, duplicate, skipped, malformed, vulnerable or fix row.
5. The two initial lock paths are pinned. After acceptance, the complete accepted tuple must remain an exact candidate prefix: future lock surfaces can only be appended at the tail and then cannot disappear, reorder or admit middle insertions.
6. Full-history checkout and pinned Python setup precede the pre-install preflight. The locked install, evidence preparation, exact-base policy validator and audit executor are each single, unconditional, failure-propagating steps in exact order under the pinned Windows job identity and unfiltered triggers.

## Evidence and exclusions

- Focused tests cover pre-install line classification, exact policy identity, report completeness, subprocess failure and sanitisation, exact-prefix history, Git-base loading, workflow order and masking.
- A real offline collector must cover the unique union of both hash locks, and a hash-enforcing pip dry run must accept the regenerated dev lock. The authoritative online query remains in PR-14C's exact-head full workflow; local corporate TLS is never converted into an exemption or weakened trust route.
- Directly affected accepted quality/workflow, reproducibility, packaging and legal tests plus cheap ASCII/version/static guards run before publication.
- No application dependency upgrade, solver, formula, standard, result, schema, Streamlit, report/manual content, package, signing, release, version, v0.93 or rejected-head implementation is included. Only the QA audit tool and its lock dependencies are added.
