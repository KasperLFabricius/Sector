# PR-14A / F-014 Windows identity and signed-release acceptance

## Exact base and ownership boundary

- Exact base: `main@006fadf287c1213d1a788538097bfa4261f14a6f`; application version `0.91`.
- Sector is authored and owned by Kasper Lindskov Fabricius. Sweco Danmark A/S is the licensed organisation for internal organisational use; it is not relabelled as author, copyright holder, publisher or software owner.
- The Windows resource therefore publishes the product, description, application/product version, file version, internal/original filename, copyright and accurate licence comment. It deliberately omits `CompanyName`, publisher, certification and approval claims.

## Frozen release boundary

1. `Sector.exe` receives an exact English/Unicode Windows version resource derived from the retained `sector.__version__`, `__author__` and `__licensee__` identity. The application version remains `0.91`; the four-part Windows file tuple is `0.91.0.0`.
2. The packaged provenance manifest retains the exact source revision and build timestamp and adds the exact product, description, author, licensee and copyright identities. PR-14C owns timestamp control and reproducibility; PR-14A makes no byte-identity claim.
3. Ordinary QA and local builds remain explicitly unsigned QA artifacts and must not be launched or distributed. The controlled release workflow is manual, environment-gated and has no path filter or automatic tag/release trigger.
4. Before dependency installation or build, the release job requires a non-empty base64 PFX, password, expected signer subject and exact 40-hex certificate thumbprint from protected secrets. Missing or malformed authority fails closed.
5. The job signs only the built `dist/Sector/Sector.exe` with SHA-256 and an RFC 3161 SHA-256 timestamp. The temporary PFX is held only in the runner temporary directory and is removed in a `finally` block.
6. Before the sole signed-artifact upload, independent verification requires Windows Authenticode status `Valid`, the expected exact subject/thumbprint, code-signing EKU, a valid certificate chain, a timestamp certificate, exact Windows product/version fields, exact packaged provenance, and both legal notice files.
7. No unsigned executable is launched. No signing certificate, password, subject, thumbprint, CompanyName, publisher, authority, reputation or approval state is fabricated in source.

## Focused evidence and exclusions

- Focused tests own source identity parsing, exact resource rendering, version bounds, manifest fields, secret preflight, package/signature metadata, workflow order, pinned actions, masking/bypass mutations and unsigned-upload prevention.
- Directly affected packaging, legal, provenance, reproducibility and workflow gates plus cheap ASCII/version/static guards run before publication.
- No solver, formula, standard, result, verdict, persistence/schema, Streamlit/UI, report/manual calculation content, cold-start optimization, reproducibility claim, executable launch, application-version increment, v0.93 feature or rejected-head implementation is included.
- Genuine corporate signing credentials are intentionally absent from source. Their absence blocks an actual release workflow run, not review and merge of this fail-closed gate.
