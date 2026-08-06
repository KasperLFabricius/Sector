# PR-14A2-R2 F-014 protected Windows signing acceptance

## Exact trust boundary

This fresh candidate starts from accepted main
`fa99c278ee52edc7b8cf635aedb848211dc0e3ac`. It adds only a manual protected
Windows signing path. The workflow can run only when dispatched from
`refs/heads/main`, always checks out `refs/heads/main`, and never uses the
dispatch value as a checkout ref or executable expression.

Immediately after the pinned checkout action, before setup, dependencies or
repository code, an inline PowerShell gate requires the user-supplied value to
be lowercase 40-hex and equal to both checked-out `HEAD` and a freshly fetched
`origin/main`. The job uses read-only repository permission, one non-cancelling
concurrency group and the protected `sector-production-signing` environment.
The checkout token is retained only to authenticate that exact-main refresh.
The gate then removes every local HTTP authentication extra-header and proves
none remains before any repository script or dependency can run.

## Credential and signing boundary

Only the signing step receives the four environment-scoped secrets: PFX bytes,
PFX password, expected SHA-1 certificate thumbprint and exact certificate
subject. The package is built from the proven source and passes an isolated
standard-library preflight plus complete package/provenance validation before
those secrets are exposed.

The signing script selects a concrete Windows SDK x64 `signtool.exe`, proves
the PFX private-key certificate has the exact expected identity and code-signing
EKU, and signs `Sector.exe` with SHA-256 file and timestamp digests through the
DigiCert RFC3161 endpoint. `signtool` and `Get-AuthenticodeSignature` must both
validate the result. The signer and timestamp certificates require their own
EKUs and online, entire-chain, no-waiver validation. Windows product/version
identity, the exact source-bound manifest and both legal notices remain gated.

The PFX is written to one GUID-named file in the runner temporary directory and
that exact file is removed in `finally`. There is no unsigned fallback and no
executable launch. Upload occurs only after every signing and verification gate
passes.

## Environment configuration outside the repository

The `sector-production-signing` environment must have genuine required
reviewers, restrict deployment to `main`, and own these four secrets:

- `SECTOR_SIGNING_PFX_BASE64`;
- `SECTOR_SIGNING_PFX_PASSWORD`;
- `SECTOR_SIGNING_THUMBPRINT`;
- `SECTOR_SIGNING_SUBJECT`.

No certificate or credential is stored in source. If genuine authority is
unavailable, the workflow remains unavailable rather than weakening a gate.

## Explicit exclusions

No executable is built, signed or launched locally by this candidate. No
automatic release trigger, GitHub Release, solver/formula/standard/result,
schema/persistence, Streamlit/UI, report/manual calculation, cold-start,
reproducibility timestamp model, application-version or v0.93 change is
included. Sector remains version `0.91`; PR-14C owns controlled publication and
the consolidated full gate.
