# PR-14A2 F-014 protected genuine-signing acceptance

## Frozen boundary

This candidate starts from accepted main
`fa99c278ee52edc7b8cf635aedb848211dc0e3ac`. It adds only the manual protected
Windows signing path. The workflow has one `workflow_dispatch` trigger, read-only
repository permission and the protected environment
`sector-production-signing`. A required exact 40-hex source commit must equal
both checked-out `HEAD` and current `origin/main`.

## Genuine signing gate

The protected environment must provide the genuine certificate PFX, password,
thumbprint and exact subject through four named secrets. The workflow has no
fallback when any secret, SDK tool, signing operation or verification fails.
The x64 `signtool.exe` is selected by its concrete parent directory. Signing
uses SHA-256 file and timestamp digests plus the DigiCert RFC3161 timestamp
service.

Before upload, Sector independently requires:

- successful `signtool verify /pa /all /v` and `Get-AuthenticodeSignature`;
- exact signer thumbprint and subject;
- code-signing and timestamp EKUs;
- online, no-waiver certificate-chain validation for signer and timestamp;
- a genuine timestamp certificate;
- exact Windows product/version/legal fields and no company/publisher field;
- exact source-bound package manifest and both legal notice files.

The temporary PFX is created under `RUNNER_TEMP` with a unique name and removed
in `finally`. Only the verified signed package reaches the source-bound upload
step. No workflow or script launches `Sector.exe`.

## Dependency lifecycle and exclusions

The workflow first runs a standard-library-only validator under `python -I -S`.
It then installs the regenerated hashed build lock, which now explicitly owns
PyYAML, and runs full semantic workflow validation. No certificate or signing
authority is stored in the repository, and no signed build is attempted by this
candidate because genuine protected credentials are not locally available.

No ordinary QA path, solver/formula/standard, result/verdict, schema,
persistence, Streamlit/UI, report/manual calculation content, cold-start,
reproducibility model, application-version or v0.93 change is included. PR-14C
owns the controlled publication build and consolidated full gate.
