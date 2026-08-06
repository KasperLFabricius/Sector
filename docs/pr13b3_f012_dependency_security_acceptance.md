# PR-13B3 / F-012 dependency-security acceptance boundary

## Exact base and fresh lineage

- Exact base: `main@1f47b8747be54b48bab6205eef111f8869e4984e`.
- Application version: `0.91`.
- Coverage, Ruff and strict mypy are accepted. This final F-012 slice owns dependency vulnerability scanning only.
- Rejected and superseded PR-13 heads remain negative evidence. No rejected head, patch, branch content or review candidate is reused.

## Frozen policy

1. One `pip-audit` invocation scans `requirements-dev.txt` and `requirements-build.txt` in that exact order. Together those flattened locks cover the runtime, QA and Windows-build dependency surfaces.
2. The PyPI vulnerability service is explicit because this route validates requirement hashes as well as vulnerability identity. `--strict`, `--require-hashes` and `--disable-pip` are mandatory; skipped, unresolved, unpinned or unhashed dependencies fail closed without a second dependency resolution.
3. The audit runs through isolated Python, has no `--fix`, `--dry-run`, `--no-deps`, alternate index or vulnerability exemption, and cannot inherit Python-path, pip-index or pip-audit configuration from the job environment.
4. Compact JSON evidence retains vulnerability IDs and aliases but omits long descriptions. The output and cache paths are fixed inside the repository, and an existing evidence file is never overwritten.
5. A successful process exit is not trusted by itself. The verifier independently reconstructs the canonical name/version inventory from both locks and requires the JSON report to contain every unique pin exactly once, no unknown or skipped row, no vulnerability and no fix record.
6. The accepted-base policy ratchet prevents either lock from disappearing or reordering. Additional future lock surfaces may only be appended and then become non-shrinking.
7. Pull-request, every-main-push and manual triggers remain unfiltered. Full-history checkout, the exact base expression, the locked QA install, one validator and one executor remain unconditional and failure-propagating.

## Evidence and exclusions

- Focused tests exercise exact policy identity, lock inventory reconstruction, duplicate/missing/extra/skipped/vulnerable report rows, subprocess failure, environment sanitisation, accepted-base shrinkage and workflow bypasses.
- A real offline `pip-audit` collection must cover the exact unique union of both hash locks. The authoritative online vulnerability query remains part of the consolidated exact-head workflow gate in PR-14C; corporate TLS failure is not converted into an exemption, alternate service or weakened certificate route.
- Directly affected coverage, Ruff, mypy, reproducibility, packaging and legal contracts plus cheap ASCII/version/static guards run before publication.
- No dependency upgrade except the audit tool and its own lock-only dependencies; no solver, formula, standard, result, schema, Streamlit, report/manual content, package, signing, release, application-version, v0.93 or rejected-head implementation is included.
